"""Read-only live replay check, or synthetic default fixtures from a saved model."""

import argparse
from decimal import Decimal
from pathlib import Path

from client import ApiError, Cooldown, LedgerClient
from config import load_config, strict_json
from market import price_at
from storage import atomic_json
from validation import number


def check_default_fixtures(model):
    # Future fixture timestamps are formula tests only, never inputs to a live agent.
    for day, expected in ((0, "67000.36767791"), (30, "69404.90274610"), (365, "91475.89718627")):
        actual = number(price_at(model, "BTC", model["epoch_unix"] + day * 86400))
        if abs(actual - Decimal(expected)) > Decimal("0.00000001"):
            raise ValueError(f"Default BTC day-{day} fixture differs; descriptor may have changed")
        print(f"Default BTC day {day}: {actual} OK (synthetic fixture)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--config", default=None, help="Private trader config for read-only live check")
    source.add_argument("--descriptor", help="Saved descriptor JSON for offline default-fixture checks")
    parser.add_argument("--default-fixtures", action="store_true",
                        help="Also test published BTC quotes; requires the unchanged default descriptor")
    args = parser.parse_args()
    api = None
    try:
        if args.descriptor:
            model = strict_json(Path(args.descriptor).read_text(encoding="utf-8"))
            model = model.get("model", model)
            check_default_fixtures(model)
            return
        config = load_config(args.config or "config.trader.json", "trader", check_only=True)
        api = LedgerClient(config["LEDGER_BASE_URL"], config["TRADER_API_KEY"], "trader")
        model = api.get("market_model.php")["model"]
        quotes = api.get("market_prices.php")["prices"]
        mismatch = any(q["model_version"] != model["version"]
                       or abs(number(price_at(model, q["symbol"], q["timestamp_unix"])) - number(q["price"]))
                       > Decimal("0.00000001") for q in quotes)
        if mismatch:
            model = api.get("market_model.php")["model"]
        for quote in quotes:
            actual = number(price_at(model, quote["symbol"], quote["timestamp_unix"]))
            if (quote["timestamp_unix"] < model["epoch_unix"] or quote["model_version"] != model["version"]
                    or abs(actual - number(quote["price"])) > Decimal("0.00000001")):
                raise ValueError("Live replay differs after refresh; agents must HOLD")
            print(f"{quote['symbol']}: live quote matches replay")
        atomic_json(Path(config["STATE_DIR"]) / "market-descriptor.json", model)
        if args.default_fixtures:
            check_default_fixtures(model)
        print("Read-only verification complete; no orders submitted.")
    except Cooldown as error:
        print(f"Ledger cooldown; wait at least {error.seconds:.1f}s")
        raise SystemExit(1) from None
    except (OSError, ApiError, ValueError, KeyError, TypeError, ArithmeticError) as error:
        print(str(error) if isinstance(error, (ApiError, ValueError)) else "Descriptor/configuration could not be validated")
        raise SystemExit(1) from None
    finally:
        if api:
            api.session.close()


if __name__ == "__main__":
    main()
