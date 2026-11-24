"""Independent review: hard rules -> model -> fresh final gate -> review."""

from datetime import datetime, timezone
from decimal import Decimal
from statistics import median

from client import ApiError, Cooldown, SessionExpired, UncertainWrite
from llm import ModelError
from market import Market, price_at
from validation import (
    ValidationError, bounded_quantity, hard_rules, number, positive_int, quantity,
    scan_news_items, validate_policy, validate_review, validate_theory, validate_trader,
)


# Goal-misalignment backstop (Week 7: "a corrupted trading agent might maximize losses").
# Each order can pass every per-order check while the account still bleeds, so the Guardian
# also tracks its own high-water mark and escalates new BUYs once the drop exceeds this limit.
DRAWDOWN_LIMIT_PCT = Decimal("3")


def portfolio_value(portfolio):
    """Total account value from the Guardian's own portfolio read (cash + holdings)."""
    if portfolio.get("total_value") is not None:
        total = number(portfolio["total_value"])
    else:
        total = number(portfolio["cash_balance"])
        for holding in portfolio.get("holdings") or []:
            if holding.get("market_value") is not None:
                total += number(holding["market_value"])
            else:
                total += quantity(holding["quantity"]) * number(holding["current_price"])
    if total <= 0:
        raise ValueError("Portfolio value must be positive")
    return total


class ProvenanceError(ValidationError):
    pass


class TheoryComplianceError(ValidationError):
    pass


def _parse_ts(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            try:
                return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                return None
    return None


def decision(kind, reason, rules, risk=100):
    return {"decision": kind, "reason": reason, "risk_score": risk,
            "modified_quantity": None, "rules_triggered": rules}


class Guardian:
    def __init__(self, api, model, store, *, provider_meta=None):
        self.api, self.model, self.store = api, model, store
        self.market = Market()
        self.provider_meta = provider_meta or {}
        self._last_layer_summary = {}

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
        try:
            theory = validate_theory(self.store.theory(pending["theory_id"], pending["theory_version"]))
        except ValidationError as error:
            raise ProvenanceError(str(error)) from None
        if theory["id"] != pending["theory_id"] or theory["version"] != pending["theory_version"]:
            raise ProvenanceError("Saved theory does not match the order")
        return theory

    def assess(self, pending, order):
        summary = {
            "hard_rules": "pending",
            "drawdown_breaker": "pending",
            "theory_provenance": "pending",
            "theory_compliance": "pending",
            "news_injection_scan": "pending",
            "anomaly_check": "pending",
            "llm_review": "skipped",
            "final_recheck": "skipped",
        }
        self._last_layer_summary = summary
        policy, portfolio, quote = self.facts(order)
        blocked, escalations = hard_rules(order, policy, portfolio, quote["price"])
        if blocked:
            summary["hard_rules"] = f"BLOCK ({', '.join(blocked)})"
            return decision("BLOCK", "Independent hard rules failed: " + ", ".join(blocked), blocked)
        if escalations:
            summary["hard_rules"] = f"ESCALATE ({', '.join(escalations)})"
            return decision("ESCALATE", "Human review required: " + ", ".join(escalations), escalations, 80)
        summary["hard_rules"] = "PASS"
        tripped = self.drawdown_check(order, portfolio)
        summary["drawdown_breaker"] = tripped["summary"]
        if tripped["decision"]:
            return tripped["decision"]
        theory = self.theory_for(pending)
        summary["theory_provenance"] = f"PASS (v{theory['version']})"
        # Guardian calculates its own strategy evidence and validates theory compliance.
        signals = self.market.signals(self.api, [quote], theory, policy, portfolio)
        proposal_time_signal = None
        try:
            validate_trader(order, theory, policy, portfolio, signals, model_output=False)
        except ValidationError as error:
            drift_verified = False
            sym = order.get("symbol")
            if (sym in signals and order.get("action") in {"BUY", "SELL"}
                    and signals[sym].get("expected_action") != order["action"]):
                created_ts = _parse_ts(pending.get("created_at"))
                now_ts = _parse_ts(quote.get("timestamp_unix"))
                if (created_ts is not None and now_ts is not None
                        and 0 <= (now_ts - created_ts) <= 120
                        and self.market.model is not None
                        and created_ts >= self.market.model["epoch_unix"]):
                    proposal_quote = {
                        "symbol": sym,
                        "price": price_at(self.market.model, sym, created_ts),
                        "timestamp_unix": int(created_ts),
                        "model_version": self.market.model["version"],
                    }
                    try:
                        proposal_signals = self.market.calculate([proposal_quote], theory, policy, portfolio)
                        validate_trader(order, theory, policy, portfolio, proposal_signals, model_output=False)
                        proposal_time_signal = proposal_signals[sym]
                        drift_verified = True
                    except ValidationError:
                        drift_verified = False
            if not drift_verified:
                summary["theory_compliance"] = "FAIL"
                raise TheoryComplianceError(str(error)) from None
        summary["theory_compliance"] = "PASS (verified at proposal tick)" if proposal_time_signal else "PASS"
        history = self.api.get("transactions.php", limit=50)["transactions"]
        news = self.api.get("market_news.php")["news"]
        news_warnings = scan_news_items(news, symbol=order["symbol"])
        untrusted_target_hits = [w for w in news_warnings if (not w["source_trusted"]) and w["matches_order_symbol"]]
        if untrusted_target_hits:
            summary["news_injection_scan"] = f"ESCALATE ({len(untrusted_target_hits)} untrusted injection hit(s))"
            return decision(
                "ESCALATE",
                "Untrusted market news contains prompt-injection instructions targeting this currency.",
                ["untrusted_news_injection"],
                85,
            )
        summary["news_injection_scan"] = "PASS" if not news_warnings else f"WARN ({len(news_warnings)} trusted/other)"
        relevant = [t for t in history if t["status"] == "EXECUTED"
                    and t["action"] in {"BUY", "SELL"} and t["symbol"] == order["symbol"]]
        anomaly = self.anomalies(order, quote, relevant, signals=signals)
        if anomaly:
            summary["anomaly_check"] = f"ESCALATE ({', '.join(anomaly)})"
            return decision("ESCALATE", "Recent behavior requires review: " + ", ".join(anomaly), anomaly, 75)
        summary["anomaly_check"] = "PASS"
        payload = {
            "order": pending, "current_quote": quote, "policy": policy,
            "portfolio": portfolio, "theory_snapshot": theory, "signals": signals,
            "recent_executed_history": relevant[:20], "news": news,
            "news_injection_warnings": news_warnings,
            "telemetry_limits": "No IP addresses, geography or key-use logs are exposed by this API.",
        }
        if proposal_time_signal is not None:
            payload["proposal_time_signal"] = proposal_time_signal
        answer = self.model.decide("guardian", payload, timeout=min(30, self.api.remaining()))
        validated = validate_review(answer, order["quantity"])
        summary["llm_review"] = f"{validated['decision']} (risk={validated['risk_score']})"
        return validated

    def drawdown_check(self, order, portfolio):
        """Update the saved high-water mark; escalate a BUY once the drop from it is too large.

        SELLs are never held back here, so stop-loss and take-profit exits still reach review.
        """
        try:
            value = portfolio_value(portfolio)
        except (ValidationError, ValueError, KeyError, TypeError, ArithmeticError):
            if order["action"] == "BUY":
                return {"summary": "ESCALATE (portfolio_value_unavailable)",
                        "decision": decision("ESCALATE", "Portfolio value could not be verified for the "
                                             "drawdown circuit breaker.", ["drawdown_value_unavailable"], 80)}
            return {"summary": "SKIP (value unavailable; SELL allowed)", "decision": None}
        state = self.store.read() or {"orders": {}}
        saved = state.get("drawdown") or {}
        peak = number(saved["peak_value"]) if saved.get("peak_value") is not None else value
        if value >= peak:
            peak = value
            state["drawdown"] = {"peak_value": format(peak, "f"),
                                 "peak_time": datetime.now(timezone.utc).isoformat()}
            self.store.save(state)
        drop_pct = (peak - value) / peak * Decimal(100)
        detail = f"{drop_pct:.2f}% below peak {peak:.2f} (limit {DRAWDOWN_LIMIT_PCT}%)"
        if drop_pct > DRAWDOWN_LIMIT_PCT and order["action"] == "BUY":
            self.store.log("drawdown_breaker_tripped", peak_value=format(peak, "f"),
                           current_value=format(value, "f"), drop_pct=format(drop_pct, ".4f"))
            return {"summary": f"ESCALATE ({detail})",
                    "decision": decision("ESCALATE", f"Drawdown circuit breaker: portfolio is {detail}; "
                                         "new purchases need human review.", ["drawdown_circuit_breaker"], 85)}
        return {"summary": f"PASS ({detail})", "decision": None}

    @staticmethod
    def anomalies(order, quote, history, signals=None):
        # A small, explainable baseline; no training or extra dependencies.
        flags = []
        amounts = sorted(number(t["executed_total"]) for t in history[:10]
                         if t.get("executed_total") is not None and number(t["executed_total"]) > 0)
        if len(history) >= 3 and len(amounts) >= 3:
            baseline = median(amounts)
            current = quantity(order["quantity"]) * number(quote["price"])
            if current > baseline * Decimal(3):
                flags.append("size_above_recent_baseline")
        action = order.get("action")
        if action in {"BUY", "SELL"} and history:
            latest = history[0]
            opposite = "SELL" if action == "BUY" else "BUY"
            exit_trigger = bool(signals and signals.get(order.get("symbol"), {}).get("exit_trigger"))
            if latest.get("action") == opposite and not exit_trigger:
                prev_ts = _parse_ts(latest.get("executed_at") or latest.get("created_at"))
                curr_ts = _parse_ts(quote.get("timestamp_unix"))
                if prev_ts is not None and curr_ts is not None and 0 <= (curr_ts - prev_ts) <= 300:
                    flags.append("rapid_direction_flip")
        return flags

    def review(self, pending, *, submit=False):
        transaction_id = positive_int(pending.get("transaction_id"))
        self._last_layer_summary = {}
        try:
            # Preserve requested price/quantity in the stored original and model payload.
            q = quantity(pending["requested_quantity"])
            exact_order = {"symbol": pending["symbol"], "action": pending["action"],
                           "quantity": format(q, "f"), "reasoning": pending["reasoning"]}
            answer = self.assess(pending, exact_order)
        except (Cooldown, SessionExpired):
            raise
        except ProvenanceError:
            self._last_layer_summary["theory_provenance"] = "ESCALATE (missing_theory_provenance)"
            answer = decision("ESCALATE", "Exact submitted theory snapshot is unavailable or mismatched.",
                              ["missing_theory_provenance"], 90)
        except TheoryComplianceError as error:
            self._last_layer_summary["theory_compliance"] = "BLOCK (theory_compliance_violation)"
            answer = decision("BLOCK", f"Order violates active submitted theory: {error}",
                              ["theory_compliance_violation"], 90)
        except ModelError as error:
            self._last_layer_summary["llm_review"] = "ESCALATE (model_failure)"
            answer = decision("ESCALATE", str(error), ["model_failure"], 90)
        except (ApiError, ValueError, KeyError, TypeError, ArithmeticError):
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
                    self._last_layer_summary["final_recheck"] = f"BLOCK ({', '.join(blocked)})"
                    answer = decision("BLOCK", "Final hard-rule recheck failed: " + ", ".join(blocked), blocked)
                elif escalations:
                    self._last_layer_summary["final_recheck"] = f"ESCALATE ({', '.join(escalations)})"
                    answer = decision("ESCALATE", "Final recheck requires human review: " + ", ".join(escalations),
                                      escalations, 80)
                else:
                    self._last_layer_summary["final_recheck"] = "PASS"
            except (Cooldown, SessionExpired):
                raise
            except (ApiError, ValueError, KeyError, TypeError, ArithmeticError):
                self._last_layer_summary["final_recheck"] = "ESCALATE (final_recheck_failed)"
                answer = decision("ESCALATE", "Fresh final evidence could not be validated.", ["final_recheck_failed"], 90)
        request = {"transaction_id": transaction_id, **answer}
        self.store.log("review_decision", transaction_id=transaction_id, review=answer, original=pending,
                       provider_meta=self.provider_meta, layer_summary=dict(self._last_layer_summary))
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
