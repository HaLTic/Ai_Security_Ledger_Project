"""Deterministic gates: a model recommendation never overrides these checks."""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext


class ValidationError(ValueError):
    """A locally authored validation explanation safe to show without raw input."""


SYMBOLS = {"BTC", "ETH", "DOGE", "XMR", "XRP", "SOL"}
CENT = Decimal("0.01")
UNIT = Decimal("1e-10")
INJECTION_PHRASES = (
    "ignore previous", "ignore all previous", "skip guardian", "bypass guardian",
    "reveal secrets", "reveal the api", "system prompt", "override policy",
)


def number(value, *, model=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise ValidationError("Expected a finite number")
    if model and isinstance(value, str):
        raise ValidationError("Model numbers must be JSON numbers")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError("Expected a finite number") from None
    if not result.is_finite() or result.adjusted() > 27:
        raise ValidationError("Number is non-finite or too large")
    return result


def quantity(value, *, model=False):
    result = number(value, model=model)
    if result <= 0 or result >= Decimal("1e18") or result.as_tuple().exponent < -10:
        raise ValidationError("Quantity must be positive, with at most 18 integer and 10 decimal digits")
    return result


def positive_int(value):
    if type(value) is not int or value <= 0:
        raise ValidationError("Expected a positive integer")
    return value


def text(value, limit):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValidationError("Expected meaningful text without NUL")
    if len(value.encode("utf-8")) > limit:
        raise ValidationError("Text exceeds byte limit")
    return value.strip()


def names(value):
    if isinstance(value, str):
        value = value.split(",") if value.strip() else []
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValidationError("Expected a list of names")
    return [v.strip().upper() for v in value if v.strip()]


def cash_amount(q, price, action):
    with localcontext() as ctx:
        ctx.prec = 80
        return (number(q) * number(price)).quantize(
            CENT, rounding=ROUND_CEILING if action == "BUY" else ROUND_FLOOR)


def policy_amount(q, price, action):
    with localcontext() as ctx:
        ctx.prec = 80
        return max(number(q) * number(price), cash_amount(q, price, action))


def bounded_quantity(budget, price):
    with localcontext() as ctx:
        ctx.prec = 80
        cents = number(budget).quantize(CENT, rounding=ROUND_FLOOR)
        return (cents / number(price)).quantize(UNIT, rounding=ROUND_FLOOR)


def validate_theory(theory):
    if not isinstance(theory, dict) or theory.get("status") != "SUBMITTED":
        raise ValidationError("A submitted theory is required")
    for key in ("id", "version", "lookback_minutes"):
        positive_int(theory.get(key))
    if theory["lookback_minutes"] > 1440:
        raise ValidationError("Lookback exceeds 1440 minutes")
    text(theory.get("title"), 120)
    for key in ("hypothesis", "entry_rule", "exit_rule", "risk_rule"):
        text(theory.get(key), 4000)
    selected = theory.get("selected_symbols")
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 6
            or any(s not in SYMBOLS for s in selected) or len(set(selected)) != len(selected)):
        raise ValidationError("Invalid theory currency selection")
    if theory.get("strategy") not in {"momentum", "mean_reversion", "custom"}:
        raise ValidationError("Unrecognised strategy")
    for key, low, high in (
        ("threshold_pct", "0.01", "50"), ("position_fraction", "0.001", "1"),
        ("stop_loss_pct", "0.01", "100"), ("take_profit_pct", "0.01", "100"),
    ):
        value = number(theory.get(key))
        if not Decimal(low) <= value <= Decimal(high) or value.as_tuple().exponent < -4:
            raise ValidationError("Invalid theory setting")
    return theory


def validate_policy(policy):
    if not isinstance(policy, dict):
        raise ValidationError("Missing policy")
    for key in ("max_transaction_amount", "escalation_threshold"):
        if number(policy.get(key)) <= 0:
            raise ValidationError("Invalid policy amount")
    for key in ("max_trades_per_hour", "max_trades_per_day", "trades_last_hour", "trades_last_day"):
        if type(policy.get(key)) is not int or policy[key] < 0:
            raise ValidationError("Invalid policy quota or count")
    for key in ("allowed_symbols", "restricted_actions"):
        names(policy.get(key))
    return policy


def holding(portfolio, symbol):
    cash = number(portfolio["cash_balance"])
    if cash < 0 or not isinstance(portfolio["holdings"], list):
        raise ValidationError("Invalid portfolio")
    found = [h for h in portfolio["holdings"] if h["symbol"] == symbol]
    if len(found) > 1:
        raise ValidationError("Duplicate portfolio position")
    item = found[0] if found else {"symbol": symbol, "quantity": 0, "avg_cost": 0}
    if number(item["quantity"]) < 0 or number(item["avg_cost"]) < 0:
        raise ValidationError("Invalid holding")
    return item


def hard_rules(order, policy, portfolio, price):
    """Return blocking rules and escalation rules; use current independent facts."""
    validate_policy(policy)
    action, symbol = order["action"], order["symbol"]
    q = quantity(order["quantity"])
    price = number(price)
    if price <= 0:
        raise ValidationError("Invalid quote")
    blocked, review = [], []
    if action not in {"BUY", "SELL"} or action in names(policy["restricted_actions"]):
        blocked.append("restricted_action")
    if symbol not in SYMBOLS or symbol not in names(policy["allowed_symbols"]):
        blocked.append("symbol_not_allowed")
    if action not in {"BUY", "SELL"}:
        return blocked, review
    amount = policy_amount(q, price, action)
    if amount > number(policy["max_transaction_amount"]):
        blocked.append("transaction_ceiling")
    if cash_amount(q, price, action) < CENT:
        blocked.append("below_minimum_value")
    for period in ("hour", "day"):
        if policy[f"trades_last_{period}"] >= policy[f"max_trades_per_{period}"]:
            blocked.append(f"{period}_quota")
    position = holding(portfolio, symbol)
    if action == "BUY" and cash_amount(q, price, action) > number(portfolio["cash_balance"]):
        blocked.append("insufficient_cash")
    if action == "SELL" and q > number(position["quantity"]):
        blocked.append("insufficient_holdings")
    if amount >= number(policy["escalation_threshold"]):
        review.append("escalation_threshold")
    reasoning = text(order.get("reasoning"), 16000).casefold()
    if any(phrase in reasoning for phrase in INJECTION_PHRASES):
        review.append("suspicious_instructions")
    return blocked, review


def validate_trader(answer, theory, policy, portfolio, signals, *, model_output=True):
    if not isinstance(answer, dict) or set(answer) != {"symbol", "action", "quantity", "reasoning"}:
        raise ValidationError("Trader output has incorrect fields")
    text(answer["reasoning"], 16000)
    if not isinstance(answer["symbol"], str):
        raise ValidationError("Symbol must be text")
    action = answer["action"]
    if action == "HOLD":
        if number(answer["quantity"], model=model_output) != 0:
            raise ValidationError("HOLD quantity must be zero")
        return answer
    if action not in {"BUY", "SELL"}:
        raise ValidationError("Invalid trading action")
    q = quantity(answer["quantity"], model=model_output)
    symbol = answer["symbol"]
    if symbol not in theory["selected_symbols"] or symbol not in signals:
        raise ValidationError("Currency is outside validated theory evidence")
    signal = signals[symbol]
    if signal["expected_action"] != action:
        raise ValidationError("Model decision does not follow the submitted theory")
    blocked, _ = hard_rules(answer, policy, portfolio, signal["price"])
    if blocked:
        raise ValidationError("Order failed hard rules: " + ", ".join(blocked))
    if action == "BUY" and q > number(signal["max_buy_quantity"]):
        raise ValidationError("Order exceeds permitted per-buy budget")
    if action == "SELL" and q > number(signal["max_sell_quantity"]):
        raise ValidationError("Order exceeds permitted sale quantity")
    return {**answer, "quantity": format(q, "f")}


def validate_review(answer, requested_quantity):
    expected = {"decision", "reason", "risk_score", "modified_quantity", "rules_triggered"}
    if not isinstance(answer, dict) or set(answer) != expected:
        raise ValidationError("Guardian output has incorrect fields")
    if answer["decision"] not in {"APPROVE", "MODIFY", "BLOCK", "ESCALATE"}:
        raise ValidationError("Invalid Guardian decision")
    text(answer["reason"], 8000)
    risk = number(answer["risk_score"], model=True)
    if not 0 <= risk <= 100 or risk.as_tuple().exponent < -2:
        raise ValidationError("Risk score must be 0..100 with at most two decimals")
    rules = answer["rules_triggered"]
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValidationError("Invalid triggered rules")
    for rule in rules:
        text(rule, 255)
    if answer["decision"] == "MODIFY":
        q = quantity(answer["modified_quantity"], model=True)
        if q >= quantity(requested_quantity):
            raise ValidationError("MODIFY must strictly decrease requested quantity")
        return {**answer, "modified_quantity": format(q, "f")}
    if answer["modified_quantity"] is not None:
        raise ValidationError("Only MODIFY can include a quantity")
    return answer
