"""Read-only Ledger live evidence exporter for each member's assigned currency.

Uses only GET requests with the role-scoped trader key (no writes, no LLM calls,
and zero API keys written into the exported JSON).
"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from client import LedgerClient
from config import load_config, strict_json
from market import price_at
from storage import atomic_json, verify_chain

TEAM_DEFAULTS = {
    "BTC": ("Zayed Alnuaimi", "100061300"),
    "ETH": ("Abdulla Alshehhi", "100061146"),
    "SOL": ("Ibrahim Alhashmi", "100059929"),
    "XRP": ("Mohamed Alromaithi", "100060448"),
}


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


def _max_drawdown_pct(values):
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for val in values:
        if val > peak:
            peak = val
        if peak > 0:
            dd = (val - peak) / peak
            if dd < worst:
                worst = dd
    return worst * 100.0


def _portfolio_total(portfolio):
    if not isinstance(portfolio, dict):
        return 0.0
    if portfolio.get("total_value") is not None:
        return float(portfolio["total_value"])
    return float(portfolio.get("cash_balance") or 0.0) + float(portfolio.get("holdings_value") or 0.0)


def summarize_account(
    coin,
    member,
    student_id,
    *,
    policy,
    portfolio,
    theory,
    model,
    transactions,
    guardian_logs,
    portfolio_samples=None,
    chains=None,
):
    coin = coin.upper()
    txs = list(transactions or [])
    glogs = list(guardian_logs or [])
    samples = list(portfolio_samples or [])

    executed = [
        t for t in txs
        if t.get("status") == "EXECUTED"
        and t.get("action") in {"BUY", "SELL"}
        and str(t.get("symbol", "")).upper() == coin
        and Decimal(str(t.get("executed_quantity") or 0)) > 0
    ]

    sample_totals = [float(s["total_value"]) for s in samples if s.get("total_value") is not None]
    start_value = sample_totals[0] if sample_totals else 100000.0
    end_value = _portfolio_total(portfolio)
    return_pct = ((end_value / start_value) - 1.0) * 100.0 if start_value > 0 else 0.0
    dd_pct = _max_drawdown_pct([start_value, *sample_totals, end_value])

    time_points = []
    for s in samples:
        ts = _parse_ts(s.get("time"))
        if ts is not None:
            time_points.append((ts, str(s.get("time"))))
    for t in txs:
        for key in ("created_at", "executed_at"):
            ts = _parse_ts(t.get(key))
            if ts is not None:
                time_points.append((ts, str(t.get(key))))
    time_points.sort(key=lambda pair: pair[0])

    buy_and_hold_pct = None
    if (
        isinstance(model, dict)
        and isinstance(model.get("assets"), dict)
        and coin in model["assets"]
        and len(time_points) >= 2
    ):
        t_start, t_end = time_points[0][0], time_points[-1][0]
        if t_end > t_start and t_start >= model.get("epoch_unix", 0):
            p0 = price_at(model, coin, t_start)
            p1 = price_at(model, coin, t_end)
            if p0 > 0:
                buy_and_hold_pct = ((p1 / p0) - 1.0) * 100.0

    verdicts = {"APPROVE": 0, "MODIFY": 0, "BLOCK": 0, "ESCALATE": 0}
    for g in glogs:
        dec = g.get("decision")
        if dec in verdicts:
            verdicts[dec] += 1

    outcomes = {"EXECUTED": 0, "BLOCKED": 0, "ESCALATED": 0, "REJECTED": 0, "PENDING": 0}
    for t in txs:
        st = t.get("status")
        if st in outcomes:
            outcomes[st] += 1

    security_events = [
        {
            "transaction_id": t.get("transaction_id"),
            "symbol": t.get("symbol"),
            "action": t.get("action"),
            "requested_quantity": t.get("requested_quantity"),
            "status": t.get("status"),
            "guardian_decision": t.get("guardian_decision"),
            "guardian_reason": t.get("guardian_reason"),
            "risk_score": t.get("risk_score"),
            "created_at": t.get("created_at"),
        }
        for t in txs
        if t.get("status") in {"BLOCKED", "ESCALATED", "REJECTED"}
    ]

    return {
        "coin": coin,
        "member": member,
        "student_id": student_id,
        "executed_fills": len(executed),
        "sample_count": len(samples),
        "start_value": round(start_value, 2),
        "end_value": round(end_value, 2),
        "portfolio_return_pct": round(return_pct, 4),
        "max_drawdown_pct": round(dd_pct, 4),
        "buy_and_hold_pct": round(buy_and_hold_pct, 4) if buy_and_hold_pct is not None else None,
        "policy": {
            "allowed_symbols": policy.get("allowed_symbols"),
            "restricted_actions": policy.get("restricted_actions"),
            "max_transaction_amount": policy.get("max_transaction_amount"),
            "escalation_threshold": policy.get("escalation_threshold"),
            "max_trades_per_hour": policy.get("max_trades_per_hour"),
            "max_trades_per_day": policy.get("max_trades_per_day"),
        } if isinstance(policy, dict) else {},
        "session_window": {
            "start": time_points[0][1] if time_points else None,
            "end": time_points[-1][1] if time_points else None,
            "theory_id": theory.get("id") if isinstance(theory, dict) else None,
            "theory_version": theory.get("version") if isinstance(theory, dict) else None,
            "strategy": theory.get("strategy") if isinstance(theory, dict) else None,
        },
        "verdicts": verdicts,
        "outcomes": outcomes,
        "security_events": security_events,
        "chains": chains or {},
    }


def _read_local_state(state_dir):
    state_dir = Path(state_dir)
    samples = []
    t_log = state_dir / "trader.jsonl"
    if t_log.exists():
        for raw in t_log.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                entry = strict_json(raw)
            except ValueError:
                continue
            if entry.get("event") == "portfolio_sample" and isinstance(entry.get("portfolio"), dict):
                samples.append({
                    "time": entry.get("time"),
                    "total_value": _portfolio_total(entry["portfolio"]),
                })
    chains = {
        "trader": verify_chain(state_dir / "trader.jsonl"),
        "guardian": verify_chain(state_dir / "guardian.jsonl"),
    }
    return samples, chains


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coin", required=True, help="Assigned currency (BTC, ETH, SOL, XRP, DOGE, XMR)")
    parser.add_argument("--config", default="config.trader.json", help="Private trader config JSON")
    parser.add_argument("--member", default=None, help="Member full name (defaults by coin)")
    parser.add_argument("--student-id", default=None, help="Student ID (defaults by coin)")
    parser.add_argument("--out", default=None, help="Output JSON path (default evidence/evidence_<COIN>.json)")
    args = parser.parse_args()

    coin = args.coin.strip().upper()
    default_member, default_id = TEAM_DEFAULTS.get(coin, ("Unknown Member", "000000000"))
    member = args.member or default_member
    student_id = args.student_id or default_id
    out_path = Path(args.out or f"evidence/evidence_{coin}.json")

    config = load_config(args.config, "trader", check_only=True)
    api = LedgerClient(config["LEDGER_BASE_URL"], config["TRADER_API_KEY"], "trader")
    try:
        policy = api.get("policies.php")
        portfolio = api.get("portfolio.php")
        theory = api.get("theory.php").get("theory")
        model = api.get("market_model.php").get("model")
        transactions = api.get("transactions.php", limit=200).get("transactions", [])
        guardian_logs = api.get("guardian_logs.php", limit=200).get("guardian_logs", [])
    finally:
        api.session.close()

    samples, chains = _read_local_state(config["STATE_DIR"])
    summary = summarize_account(
        coin, member, student_id,
        policy=policy, portfolio=portfolio, theory=theory, model=model,
        transactions=transactions, guardian_logs=guardian_logs,
        portfolio_samples=samples, chains=chains,
    )
    atomic_json(out_path, summary)
    print(
        f"Exported {out_path}: {coin} ({member}) | EXECUTED fills={summary['executed_fills']} "
        f"| Return={summary['portfolio_return_pct']:+.4f}% | Security events={len(summary['security_events'])}"
    )


if __name__ == "__main__":
    main()
