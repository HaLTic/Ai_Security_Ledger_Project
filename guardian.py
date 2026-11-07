"""Independent review: hard rules -> model -> fresh final gate -> review."""

from decimal import Decimal
from statistics import median

from client import ApiError, Cooldown, SessionExpired, UncertainWrite
from llm import ModelError
from market import Market
from validation import (
    bounded_quantity, hard_rules, number, positive_int, quantity, validate_policy,
    validate_review, validate_theory, validate_trader,
)


def decision(kind, reason, rules, risk=100):
    return {"decision": kind, "reason": reason, "risk_score": risk,
            "modified_quantity": None, "rules_triggered": rules}


class Guardian:
    def __init__(self, api, model, store):
        self.api, self.model, self.store = api, model, store
        self.market = Market()

    def facts(self, order):
        policy = validate_policy(self.api.get("policies.php"))
        portfolio = self.api.get("portfolio.php")
        quotes = self.api.get("market_prices.php", symbols=order["symbol"])["prices"]
        matches = [q for q in quotes if q["symbol"] == order["symbol"]]
        if len(matches) != 1:
            raise ValueError("Missing unique independent quote")
        price = number(matches[0]["price"])
        if price <= 0:
            raise ValueError("Invalid current quote")
        return policy, portfolio, matches[0]

    def theory_for(self, pending):
        current = self.api.get("theory.php")["theory"]
        if (current and current.get("id") == pending["theory_id"]
                and current.get("version") == pending["theory_version"]):
            self.store.snapshot(validate_theory(current))
        theory = validate_theory(self.store.theory(pending["theory_id"], pending["theory_version"]))
        if theory["id"] != pending["theory_id"] or theory["version"] != pending["theory_version"]:
            raise ValueError("Saved theory does not match the order")
        return theory

    def assess(self, pending, order):
        policy, portfolio, quote = self.facts(order)
        blocked, escalations = hard_rules(order, policy, portfolio, quote["price"])
        if blocked:
            return decision("BLOCK", "Independent hard rules failed: " + ", ".join(blocked), blocked)
        if escalations:
            return decision("ESCALATE", "Human review required: " + ", ".join(escalations), escalations, 80)
        theory = self.theory_for(pending)
        # Guardian calculates its own strategy evidence and validates theory compliance.
        signals = self.market.signals(self.api, [quote], theory, policy, portfolio)
        validate_trader(order, theory, policy, portfolio, signals, model_output=False)
        history = self.api.get("transactions.php", limit=50)["transactions"]
        news = self.api.get("market_news.php")["news"]
        relevant = [t for t in history if t["status"] == "EXECUTED"
                    and t["action"] in {"BUY", "SELL"} and t["symbol"] == order["symbol"]]
        anomaly = self.anomalies(order, quote, relevant)
        if anomaly:
            return decision("ESCALATE", "Recent behavior requires review: " + ", ".join(anomaly), anomaly, 75)
        payload = {
            "order": pending, "current_quote": quote, "policy": policy,
            "portfolio": portfolio, "theory_snapshot": theory, "signals": signals,
            "recent_executed_history": relevant[:20], "news": news,
            "telemetry_limits": "No IP addresses, geography or key-use logs are exposed by this API.",
        }
        answer = self.model.decide("guardian", payload, timeout=min(30, self.api.remaining()))
        return validate_review(answer, order["quantity"])

    @staticmethod
    def anomalies(order, quote, history):
        # A small, explainable baseline; no training or extra dependencies.
        if len(history) < 3:
            return []
        amounts = sorted(number(t["executed_total"]) for t in history[:10]
                         if t.get("executed_total") is not None and number(t["executed_total"]) > 0)
        if len(amounts) < 3:
            return []
        baseline = median(amounts)
        current = quantity(order["quantity"]) * number(quote["price"])
        return ["size_above_recent_baseline"] if current > baseline * Decimal(3) else []

    def review(self, pending, *, submit=False):
        transaction_id = positive_int(pending.get("transaction_id"))
        try:
            # Preserve requested price/quantity in the stored original and model payload.
            q = quantity(pending["requested_quantity"])
            exact_order = {"symbol": pending["symbol"], "action": pending["action"],
                           "quantity": format(q, "f"), "reasoning": pending["reasoning"]}
            answer = self.assess(pending, exact_order)
        except (Cooldown, SessionExpired):
            raise
        except (ApiError, ModelError, ValueError, KeyError, TypeError, ArithmeticError):
            answer = decision("ESCALATE", "Required context, provenance or model judgment could not be validated.",
                              ["evidence_or_model_failure"], 90)
        if answer["decision"] in {"APPROVE", "MODIFY"}:
            try:
                final_order = {**exact_order, "quantity": (
                    answer["modified_quantity"] if answer["decision"] == "MODIFY" else format(q, "f"))}
                policy, portfolio, quote = self.facts(final_order)
                blocked, escalations = hard_rules(final_order, policy, portfolio, quote["price"])
                if final_order["action"] == "BUY":
                    theory = self.store.theory(pending["theory_id"], pending["theory_version"])
                    budget = min(number(portfolio["cash_balance"]) * number(theory["position_fraction"]),
                                 number(policy["max_transaction_amount"]))
                    if quantity(final_order["quantity"]) > bounded_quantity(budget, quote["price"]):
                        blocked.append("per_buy_fraction")
                if blocked:
                    answer = decision("BLOCK", "Final hard-rule recheck failed: " + ", ".join(blocked), blocked)
                elif escalations:
                    answer = decision("ESCALATE", "Final recheck requires human review: " + ", ".join(escalations),
                                      escalations, 80)
            except (Cooldown, SessionExpired):
                raise
            except (ApiError, ValueError, KeyError, TypeError, ArithmeticError):
                answer = decision("ESCALATE", "Fresh final evidence could not be validated.", ["final_recheck_failed"], 90)
        request = {"transaction_id": transaction_id, **answer}
        self.store.log("review_decision", transaction_id=transaction_id, review=answer, original=pending)
        if not submit:
            print(f"PREVIEW: transaction {transaction_id} -> {answer['decision']}; no review sent.")
            return
        state = self.store.read() or {"orders": {}}
        state["orders"][str(transaction_id)] = {"phase": "sending", "request": request, "original": pending}
        self.store.save(state)
        try:
            reply = self.api.post("trade_review.php", request)
            if (reply.get("transaction_id") != transaction_id
                    or reply.get("status") not in {"EXECUTED", "BLOCKED", "REJECTED", "ESCALATED"}):
                raise UncertainWrite("Review response could not be confirmed")
            if reply["status"] == "EXECUTED" and not isinstance(reply.get("fill"), dict):
                # An idempotent response can omit a fill. Confirm through history next cycle.
                raise UncertainWrite("Execution needs confirmation from transaction history")
        except UncertainWrite:
            state["orders"][str(transaction_id)]["phase"] = "uncertain"
            self.store.save(state)
            raise
        state["orders"][str(transaction_id)] = {"phase": "finished", "status": reply["status"]}
        self.store.save(state)
        self.store.log("review_result", transaction_id=transaction_id, result=reply)
        print(f"Transaction {transaction_id}: {reply['status']}")

    def reconcile(self):
        state = self.store.read()
        if not state or not any(s["phase"] in {"sending", "uncertain"} for s in state["orders"].values()):
            return
        history = self.api.get("transactions.php", limit=200)["transactions"]
        for entry in history:
            key = str(entry["transaction_id"])
            if key in state["orders"] and state["orders"][key]["phase"] in {"sending", "uncertain"}:
                if entry["status"] in {"EXECUTED", "BLOCKED", "REJECTED", "ESCALATED"}:
                    state["orders"][key] = {"phase": "finished", "status": entry["status"]}
                    self.store.log("review_reconciled", transaction_id=entry["transaction_id"], status=entry["status"])
        self.store.save(state)

    def cycle(self, *, submit=False):
        self.reconcile()
        pending = self.api.get("trade_pending.php", limit=2)["pending"]
        if not isinstance(pending, list):
            raise ValueError("Invalid pending queue")
        if not pending:
            print("Guardian: no pending orders.")
        for order in pending:
            try:
                # A still-pending order is reassessed from fresh evidence, not replayed blindly.
                self.review(order, submit=submit)
            except (Cooldown, SessionExpired):
                raise
            except Exception as error:
                self.store.log("review_error", transaction_id=order.get("transaction_id"), error=type(error).__name__)
                print("Guardian left an order pending:", type(error).__name__)


if __name__ == "__main__":
    from runner import run
    run("guardian")
