"""Public price replay and a deliberately small momentum/mean-reversion strategy.

Replay follows the course guide Appendix A, including integer noise and rounding.
"""

from decimal import Decimal
import math
import time

from validation import ValidationError, bounded_quantity, holding, names, number, validate_policy, validate_theory


def price_at(model, symbol, timestamp):
    step = model["tick_seconds"]
    tick = max(0, math.floor((timestamp - model["epoch_unix"]) / step))
    seconds = tick * step
    asset = model["assets"][symbol]
    ratio = seconds / 86400 / model["power_timescale_days"]
    trend = asset["base_price"] * (1 + ratio) ** asset["power_exponent"]
    wave = sum(
        amplitude * math.sin(2 * math.pi * (seconds / cycle["period_seconds"])
                             + asset["phase"] + cycle["phase"])
        for amplitude, cycle in zip(asset["cycle_amplitudes"], model["cycles"])
    )
    modulus, multiplier = model["noise_modulus"], model["noise_multiplier"]
    x = (tick + asset["noise_seed"]) % modulus
    x = x * multiplier % modulus
    x = x * multiplier % modulus
    noise = 2 * x / modulus - 1
    raw = trend * math.exp(wave + asset["noise_amplitude"] * noise)
    clamped = min(model["max_price"], max(model["min_price"], raw))
    return math.floor(clamped * 1e8 + 0.5) / 1e8


def sample_signal(model, quote, lookback):
    now = quote["timestamp_unix"]
    if type(now) is not int or now < model["epoch_unix"]:
        raise ValidationError("Invalid quote timestamp")
    start = now - lookback * 60
    if start < model["epoch_unix"]:
        raise ValidationError("Insufficient history for theory lookback")
    if quote["model_version"] != model["version"]:
        raise ValidationError("Market descriptor version mismatch")
    samples = [number(price_at(model, quote["symbol"], start + (now - start) * i / 60))
               for i in range(61)]
    current = number(quote["price"])
    if current <= 0 or abs(samples[-1] - current) > Decimal("0.00000001"):
        raise ValidationError("Current quote does not match price replay")
    return {
        "price": str(current), "timestamp_unix": now,
        "return_pct": str((current / samples[0] - 1) * 100),
        "mean_deviation_pct": str((current / (sum(samples) / 61) - 1) * 100),
    }


class Market:
    def __init__(self):
        self.model = None
        self.fetched_at = 0.0

    def signals(self, api, quotes, theory, policy, portfolio):
        validate_theory(theory)
        validate_policy(policy)
        if theory["strategy"] == "custom":
            raise ValidationError("This basic implementation supports momentum and mean_reversion; select one")
        if (self.model is None or time.monotonic() - self.fetched_at > 180
                or any(q["model_version"] != self.model["version"] for q in quotes)):
            self.refresh(api)
        try:
            signals = self.calculate(quotes, theory, policy, portfolio)
        except ValueError:
            self.refresh(api)
            signals = self.calculate(quotes, theory, policy, portfolio)
        return signals

    def refresh(self, api):
        self.model = api.get("market_model.php")["model"]
        self.fetched_at = time.monotonic()

    def calculate(self, quotes, theory, policy, portfolio):
        signals = {}
        eligible = set(theory["selected_symbols"]) & set(names(policy["allowed_symbols"]))
        for quote in quotes:
            symbol = quote["symbol"]
            if symbol not in eligible:
                continue
            if symbol in signals:
                raise ValidationError("Duplicate market quote")
            signal = sample_signal(self.model, quote, theory["lookback_minutes"])
            price = number(signal["price"])
            position = holding(portfolio, symbol)
            held, cost = number(position["quantity"]), number(position["avg_cost"])
            threshold = number(theory["threshold_pct"])
            value = number(signal["return_pct"] if theory["strategy"] == "momentum"
                           else signal["mean_deviation_pct"])
            if theory["strategy"] == "mean_reversion":
                value = -value
            gain = (price / cost - 1) * 100 if held > 0 and cost > 0 else Decimal(0)
            exit_trigger = held > 0 and cost > 0 and (
                gain <= -number(theory["stop_loss_pct"])
                or gain >= number(theory["take_profit_pct"]))
            # Tolerance applies only to computed signals, never to money or policy.
            tolerance = Decimal("1e-10")
            action = "HOLD"
            if exit_trigger or (held > 0 and value <= -threshold + tolerance):
                action = "SELL"
            elif value >= threshold - tolerance:
                action = "BUY"
            if action in names(policy["restricted_actions"]):
                action = "HOLD"
            budget = min(number(portfolio["cash_balance"]) * number(theory["position_fraction"]),
                         number(policy["max_transaction_amount"]))
            signals[symbol] = {
                **signal, "signal_pct": str(value), "expected_action": action,
                "exit_trigger": bool(exit_trigger), "buy_budget": str(budget),
                "max_buy_quantity": str(bounded_quantity(budget, price)),
                "max_sell_quantity": str(min(held, bounded_quantity(policy["max_transaction_amount"], price))),
            }
        if set(signals) != eligible:
            raise ValidationError("Missing eligible market quotes")
        return signals
