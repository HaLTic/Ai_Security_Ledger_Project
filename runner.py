"""Shared CLI. Running without --submit previews decisions without Ledger writes."""

import argparse
import random
import time

from client import ApiError, Cooldown, LedgerClient, SessionExpired, UncertainWrite
from config import load_config
from llm import OpenAIModel
from storage import Store


def run(role):
    parser = argparse.ArgumentParser(description=f"Ledger {role}: preview by default")
    parser.add_argument("--config", default=f"config.{role}.json", help="Private role JSON configuration")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run one cycle (default)")
    mode.add_argument("--loop", action="store_true", help="Repeat cycles for a bounded session")
    mode.add_argument("--check", action="store_true", help="Verify role credentials with read-only requests")
    parser.add_argument("--submit", action="store_true", help="Send proposals/reviews to simulated Ledger")
    parser.add_argument("--interval", type=float, default=60 if role == "trader" else 15)
    parser.add_argument("--duration", type=float, default=600, help="Session cap in seconds, at most 600")
    if role == "trader":
        recovery = parser.add_mutually_exclusive_group()
        recovery.add_argument("--resolve-id", type=int, help="Link uncertain saved intent to a verified Ledger ID")
        recovery.add_argument("--confirm-no-order", action="store_true",
                              help="Assert you verified on the dashboard that the uncertain write created no order")
    args = parser.parse_args()
    minimum = 60 if role == "trader" else 15
    if not minimum <= args.interval <= 3600 or not 1 <= args.duration <= 600:
        parser.error(f"Interval must be {minimum}..3600 seconds; duration must be 1..600 seconds")
    recovering = role == "trader" and (args.resolve_id is not None or args.confirm_no_order)
    if recovering and (args.loop or args.submit or args.check):
        parser.error("Run recovery separately from trading, checks and loops")
    api = None
    try:
        config = load_config(args.config, role, check_only=args.check or recovering)
        api = LedgerClient(config["LEDGER_BASE_URL"], config[f"{role.upper()}_API_KEY"], role,
                           deadline=time.monotonic() + args.duration)
        startup_endpoint = "portfolio.php" if role == "trader" else "policies.php"
        api.get(startup_endpoint)
        print(f"{role.capitalize()} credential check passed.")
        if args.check:
            print("Read-only check complete; no model calls or Ledger writes made.")
            return
        store = Store(config["STATE_DIR"], role)
        model = OpenAIModel(config["OPENAI_API_KEY"], config["OPENAI_MODEL"])
        if role == "trader":
            from trader import Trader
            agent = Trader(api, model, store)
        else:
            from guardian import Guardian
            agent = Guardian(api, model, store)
        with store.lock():
            if recovering:
                agent.recover(transaction_id=args.resolve_id, confirm_no_order=args.confirm_no_order)
                return
            print("SUBMIT enabled: simulated Ledger writes permitted." if args.submit else
                  "PREVIEW mode: model calls permitted, Ledger writes disabled.")
            while True:
                cooldown = 0
                try:
                    agent.cycle(submit=args.submit)
                except Cooldown as error:
                    cooldown = error.seconds
                    print(f"Ledger cooldown: wait at least {cooldown:.1f}s; orders remain pending.")
                except UncertainWrite:
                    print("Write result uncertain. Saved state will require reconciliation before another proposal.")
                except SessionExpired:
                    break
                except ApiError as error:
                    explain_api_error(error)
                except Exception as error:
                    store.log("cycle_error", error=type(error).__name__)
                    print(f"Cycle stopped safely: {type(error).__name__}. No unvalidated action will be sent.")
                if not args.loop:
                    break
                api.pause(max(args.interval, cooldown) + random.uniform(0, 2))
    except SessionExpired:
        print("Session time limit reached; restart later after reviewing outstanding orders.")
    except ApiError as error:
        explain_api_error(error)
        raise SystemExit(1) from None
    except Cooldown as error:
        print(f"Ledger startup cooldown: wait at least {error.seconds:.1f}s.")
        raise SystemExit(1) from None
    except (OSError, ValueError, RuntimeError) as error:
        # Config validation messages are fixed strings and never echo secret values.
        if isinstance(error, (ValueError, RuntimeError)):
            print(str(error))
        else:
            print("Could not access a configuration/state file; check its path and permissions.")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Stopped. Saved unresolved work will be reconciled on restart.")
    finally:
        if api is not None:
            api.session.close()


def explain_api_error(error):
    print(str(error))
    if error.status == 401:
        print("Use the complete original key; revoke and replace a lost or invalid key.")
    elif error.status == 403:
        print("Check this program has its own role-scoped key; never substitute a full key.")
