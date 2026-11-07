"""Trading Agent: gather facts -> model -> local gate -> one proposal."""

from client import ApiError, Cooldown, SessionExpired, UncertainWrite
from llm import ModelError
from market import Market
from storage import utc_now
from validation import ValidationError, names, validate_policy, validate_theory, validate_trader

UNRESOLVED = {"PENDING", "ESCALATED"}
FINAL = {"EXECUTED", "BLOCKED", "REJECTED"}


class Trader:
    def __init__(self, api, model, store):
        self.api, self.model, self.store = api, model, store
        self.market = Market()

    def hold(self, reason):
        self.store.log("hold", reason=reason)
        print("HOLD:", reason)

    def reconcile(self):
        state = self.store.read()
        # Persisted intent with a missing response can never be cleared by guessing.
        if state and state.get("phase") in {"sending", "uncertain"}:
            self.hold("Uncertain earlier proposal. Inspect Ledger history and use the recovery command.")
            return False
        recent = self.api.get("transactions.php", limit=200)["transactions"]
        if not isinstance(recent, list):
            raise ValueError("Invalid transaction history")
        if state and state.get("phase") == "pending":
            match = next((t for t in recent if t["transaction_id"] == state["transaction_id"]), None)
            if match is None:
                self.hold("Stored transaction is outside available history; reconcile on the dashboard.")
                return False
            if match["status"] not in FINAL:
                self.hold("Earlier order is still pending or escalated.")
                return False
            self.store.log("proposal_finalized", transaction_id=match["transaction_id"], status=match["status"])
            self.store.save({"phase": "resolved", "transaction_id": match["transaction_id"]})
        # Query unresolved statuses separately so an old escalation is not hidden by recent history.
        for status in UNRESOLVED:
            if self.api.get("transactions.php", status=status, limit=200)["transactions"]:
                self.hold("Account has unresolved orders; finish their review before proposing.")
                return False
        return True

    def cycle(self, *, submit=False):
        if not self.reconcile():
            return
        policy = validate_policy(self.api.get("policies.php"))
        for period in ("hour", "day"):
            if policy[f"trades_last_{period}"] >= policy[f"max_trades_per_{period}"]:
                self.hold(f"Executed-trade {period} quota is exhausted.")
                return
        stage = "Theory validation"
        try:
            theory = self.api.get("theory.php")["theory"]
            if theory is None:
                self.hold("No active submitted theory. Open Ledger > Theory Submission, submit and activate your theory.")
                return
            theory = validate_theory(theory)
            eligible = set(theory["selected_symbols"]) & set(names(policy["allowed_symbols"]))
            if not eligible:
                self.hold("Theory and policy have no eligible currency in common.")
                return
            stage = "Theory snapshot"
            self.store.snapshot(theory)
            stage = "Market quotes"
            quotes = self.api.get("market_prices.php", symbols=",".join(sorted(eligible)))["prices"]
            stage = "Portfolio evidence"
            portfolio = self.api.get("portfolio.php")
            self.store.log("portfolio_sample", portfolio=portfolio, theory_id=theory["id"],
                           theory_version=theory["version"])
            stage = "Market news"
            news = self.api.get("market_news.php")["news"]
            stage = "Price replay and signals"
            signals = self.market.signals(self.api, quotes, theory, policy, portfolio)
            payload = {"theory": theory, "policy": policy, "portfolio": portfolio,
                       "signals": signals, "news": news}
            stage = "Model request"
            answer = self.model.decide("trader", payload, timeout=min(30, self.api.remaining()))
            stage = "Model output validation"
            order = validate_trader(answer, theory, policy, portfolio, signals)
        except (Cooldown, SessionExpired):
            raise
        except (ModelError, ValidationError) as error:
            self.hold(f"{stage}: {error} No proposal sent.")
            return
        except (ValueError, KeyError, TypeError, ArithmeticError) as error:
            # Unexpected third-party exceptions may contain response text or secrets.
            self.hold(f"{stage} failed ({type(error).__name__}); received data could not be validated. No proposal sent.")
            return
        self.store.log("trader_decision", theory_id=theory["id"], theory_version=theory["version"],
                       signals=signals, decision=order)
        if order["action"] == "HOLD":
            self.hold(order["reasoning"])
            return
        proposal = {**order, "theory_id": theory["id"]}
        if not submit:
            print(f"PREVIEW: {order['action']} {order['quantity']} {order['symbol']}; no proposal sent.")
            return
        state = {"phase": "sending", "intent": proposal, "theory_version": theory["version"],
                 "started_at": utc_now()}
        self.store.save(state)
        try:
            reply = self.api.post("trade_propose.php", proposal)
        except UncertainWrite:
            self.store.save({**state, "phase": "uncertain"})
            raise
        except Cooldown:
            # A 429 refused this write; a 503 would have raised UncertainWrite.
            self.store.save({**state, "phase": "not_submitted"})
            raise
        except ApiError:
            # A logged restricted-action rejection may have a transaction record.
            # Preserve the intent for explicit reconciliation rather than assuming no write.
            self.store.save({**state, "phase": "uncertain"})
            raise
        # Unexpected exceptions deliberately leave the intent in 'sending'.
        transaction_id = reply.get("transaction_id")
        if type(transaction_id) is not int or transaction_id <= 0 or reply.get("status") != "PENDING":
            self.store.save({**state, "phase": "uncertain"})
            raise UncertainWrite("Proposal reply did not confirm a pending transaction")
        self.store.save({**state, "phase": "pending", "transaction_id": transaction_id})
        self.store.log("proposal_submitted", transaction_id=transaction_id, status=reply["status"])
        print(f"Proposed transaction {transaction_id}: PENDING")

    def recover(self, *, transaction_id=None, confirm_no_order=False):
        state = self.store.read()
        if not state or state.get("phase") not in {"sending", "uncertain", "pending"}:
            raise ValueError("There is no unresolved local proposal to recover")
        if confirm_no_order:
            if state.get("transaction_id"):
                raise ValueError("A known transaction cannot be discarded; use --resolve-id")
            # This flag is an explicit human assertion after checking the dashboard.
            self.store.log("manual_recovery_no_order", previous_intent=state)
            self.store.save({"phase": "resolved", "resolution": "human_verified_no_order"})
            print("Recorded your dashboard verification that no order was created.")
            return
        history = self.api.get("transactions.php", limit=200)["transactions"]
        match = next((t for t in history if t["transaction_id"] == transaction_id), None)
        if match is None:
            raise ValueError("Transaction not found in available history; inspect the dashboard")
        intent = state["intent"]
        from validation import number
        if (match["symbol"] != intent["symbol"] or match["action"] != intent["action"]
                or number(match["requested_quantity"]) != number(intent["quantity"])
                or match["theory_id"] != intent["theory_id"]
                or match["theory_version"] != state["theory_version"]
                or match["status"] not in FINAL | UNRESOLVED):
            raise ValueError("Selected transaction does not match the saved intent")
        phase = "pending" if match["status"] in UNRESOLVED else "resolved"
        self.store.save({**state, "phase": phase, "transaction_id": transaction_id})
        self.store.log("manual_recovery_linked", transaction_id=transaction_id, status=match["status"])
        print(f"Linked saved intent to transaction {transaction_id}: {match['status']}")


if __name__ == "__main__":
    from runner import run
    run("trader")
