"""Read-only loopback SOC Audit Dashboard connected strictly to real .state/ logs.

Strictly read-only: never reads private config*.json files, never imports LedgerClient
or LLM providers, and never renders or handles API credentials.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from config import strict_json
from storage import verify_chain


def _read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    items = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            try:
                items.append(strict_json(raw))
            except ValueError:
                continue
    return items


def _read_json_optional(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return strict_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def _extract_provider(entries, fallback_role):
    for entry in reversed(entries):
        if entry.get("event") == "session_start" and entry.get("provider"):
            return {"provider": entry["provider"], "model": entry.get("model", "unknown")}
        meta = entry.get("provider_meta")
        if isinstance(meta, dict) and meta.get("provider"):
            return {"provider": meta["provider"], "model": meta.get("model", "unknown")}
    return {"provider": "not_started", "model": f"{fallback_role}-idle"}


def _safe_theories(state_dir):
    theories_dir = Path(state_dir) / "theories"
    if not theories_dir.exists():
        return []
    out = []
    for path in sorted(theories_dir.glob("*.json")):
        obj = _read_json_optional(path, None)
        if isinstance(obj, dict):
            out.append({
                "id": obj.get("id"),
                "version": obj.get("version"),
                "title": obj.get("title"),
                "strategy": obj.get("strategy"),
                "selected_symbols": obj.get("selected_symbols", []),
                "lookback_minutes": obj.get("lookback_minutes"),
                "threshold_pct": obj.get("threshold_pct"),
                "position_fraction": obj.get("position_fraction"),
            })
    return out


def _safe_journals(state_dir):
    state_dir = Path(state_dir)
    t_state = _read_json_optional(state_dir / "trader.json", None)
    g_state = _read_json_optional(state_dir / "guardian.json", None)
    trader_summary = None
    if isinstance(t_state, dict):
        trader_summary = {
            "phase": t_state.get("phase"),
            "transaction_id": t_state.get("transaction_id"),
            "theory_version": t_state.get("theory_version"),
            "started_at": t_state.get("started_at"),
        }
    guardian_summary = None
    if isinstance(g_state, dict) and isinstance(g_state.get("orders"), dict):
        orders = g_state["orders"]
        guardian_summary = {
            "tracked_orders": len(orders),
            "unresolved": [
                {"transaction_id": k, "phase": v.get("phase"), "status": v.get("status")}
                for k, v in orders.items()
                if isinstance(v, dict) and v.get("phase") != "finished"
            ],
        }
    return {"trader": trader_summary, "guardian": guardian_summary}


def collect_events(state_dir):
    state_dir = Path(state_dir)
    trader_entries = _read_jsonl(state_dir / "trader.jsonl")
    guardian_entries = _read_jsonl(state_dir / "guardian.jsonl")

    by_tx = {}
    events = []

    pending_trader_dec = None
    for entry in trader_entries:
        ev = entry.get("event")
        if ev == "trader_decision":
            pending_trader_dec = entry
        elif ev == "proposal_submitted":
            tid = entry.get("transaction_id")
            if tid is not None:
                by_tx[tid] = {
                    "kind": "transaction",
                    "transaction_id": tid,
                    "time": entry.get("time"),
                    "trader_decision": pending_trader_dec,
                    "proposal_submitted": entry,
                    "review_decision": None,
                    "review_result": None,
                    "final_status": entry.get("status", "PENDING"),
                }
            pending_trader_dec = None
        elif ev == "proposal_finalized":
            tid = entry.get("transaction_id")
            if tid in by_tx and entry.get("status"):
                by_tx[tid]["final_status"] = entry["status"]
        elif ev == "hold":
            dec = pending_trader_dec if pending_trader_dec and pending_trader_dec.get("decision", {}).get("action") == "HOLD" else None
            events.append({
                "kind": "hold",
                "transaction_id": None,
                "time": entry.get("time"),
                "symbol": (dec or {}).get("decision", {}).get("symbol") or "LOCAL",
                "action": "HOLD",
                "quantity": "0",
                "reason": entry.get("reason"),
                "trader_decision": dec,
                "review_decision": None,
                "review_result": None,
                "final_status": "HOLD_LOCAL",
                "risk_score": 0,
                "rules_triggered": [],
                "record_hash": entry.get("record_hash"),
                "prev_hash": entry.get("prev_hash"),
                "seq": entry.get("seq"),
            })
            pending_trader_dec = None

    for entry in guardian_entries:
        ev = entry.get("event")
        tid = entry.get("transaction_id")
        if tid is None:
            continue
        item = by_tx.setdefault(tid, {
            "kind": "transaction",
            "transaction_id": tid,
            "time": entry.get("time"),
            "trader_decision": None,
            "proposal_submitted": None,
            "review_decision": None,
            "review_result": None,
            "final_status": "PENDING",
        })
        if ev == "review_decision":
            item["review_decision"] = entry
            item["time"] = entry.get("time") or item["time"]
        elif ev == "review_result":
            item["review_result"] = entry
            item["final_status"] = (entry.get("result") or {}).get("status", item["final_status"])
        elif ev == "review_reconciled":
            item["final_status"] = entry.get("status", item["final_status"])

    for tid in sorted(by_tx):
        item = by_tx[tid]
        rev_entry = item["review_decision"] or {}
        rev = rev_entry.get("review") or {}
        orig = rev_entry.get("original") or {}
        t_dec = (item["trader_decision"] or {}).get("decision") or {}
        events.append({
            "kind": "transaction",
            "transaction_id": tid,
            "time": item["time"],
            "symbol": orig.get("symbol") or t_dec.get("symbol") or "?",
            "action": orig.get("action") or t_dec.get("action") or "?",
            "quantity": str(orig.get("requested_quantity") or t_dec.get("quantity") or "?"),
            "requested_price": orig.get("requested_price"),
            "trader_reasoning": orig.get("reasoning") or t_dec.get("reasoning") or "",
            "guardian_decision": rev.get("decision", "PENDING"),
            "guardian_reason": rev.get("reason", "Awaiting Guardian review."),
            "risk_score": rev.get("risk_score", 0),
            "modified_quantity": rev.get("modified_quantity"),
            "rules_triggered": rev.get("rules_triggered") or [],
            "layer_summary": rev_entry.get("layer_summary") or {},
            "trader_signals": (item["trader_decision"] or {}).get("signals") or {},
            "review_result": (item["review_result"] or {}).get("result"),
            "final_status": item["final_status"],
            "record_hash": rev_entry.get("record_hash") or (item["proposal_submitted"] or {}).get("record_hash"),
            "prev_hash": rev_entry.get("prev_hash") or (item["proposal_submitted"] or {}).get("prev_hash"),
            "seq": rev_entry.get("seq"),
        })

    events.sort(key=lambda e: (e.get("time") or "", e.get("transaction_id") or 0), reverse=True)
    return events


def collect_portfolio(state_dir):
    state_dir = Path(state_dir)
    trader_entries = _read_jsonl(state_dir / "trader.jsonl")
    samples = []
    for entry in trader_entries:
        if entry.get("event") != "portfolio_sample":
            continue
        pf = entry.get("portfolio")
        if not isinstance(pf, dict):
            continue
        total_val = pf.get("total_value")
        if total_val is None:
            cash = float(pf.get("cash_balance") or 0)
            h_val = float(pf.get("holdings_value") or 0)
            total_val = cash + h_val
        samples.append({
            "time": entry.get("time"),
            "theory_id": entry.get("theory_id"),
            "theory_version": entry.get("theory_version"),
            "cash_balance": pf.get("cash_balance"),
            "holdings_value": pf.get("holdings_value"),
            "total_value": float(total_val),
            "holdings": pf.get("holdings") or [],
        })

    return_pct = None
    max_drawdown_pct = None
    if samples:
        start_val = samples[0]["total_value"] or 100000.0
        end_val = samples[-1]["total_value"]
        if start_val > 0:
            return_pct = ((end_val / start_val) - 1.0) * 100.0
        peak = samples[0]["total_value"]
        worst = 0.0
        for s in samples:
            val = s["total_value"]
            if val > peak:
                peak = val
            if peak > 0:
                dd = (val - peak) / peak
                if dd < worst:
                    worst = dd
        max_drawdown_pct = worst * 100.0

    return {
        "sample_count": len(samples),
        "latest": samples[-1] if samples else None,
        "return_pct": return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "samples": list(reversed(samples[-50:])),
    }


def collect_overview(state_dir):
    state_dir = Path(state_dir)
    trader_entries = _read_jsonl(state_dir / "trader.jsonl")
    guardian_entries = _read_jsonl(state_dir / "guardian.jsonl")
    trader_chain = verify_chain(state_dir / "trader.jsonl")
    guardian_chain = verify_chain(state_dir / "guardian.jsonl")
    events = collect_events(state_dir)
    theories = _safe_theories(state_dir)

    verdicts = {"APPROVE": 0, "MODIFY": 0, "BLOCK": 0, "ESCALATE": 0, "HOLD": 0}
    outcomes = {"EXECUTED": 0, "BLOCKED": 0, "ESCALATED": 0, "REJECTED": 0, "PENDING": 0}
    for ev in events:
        if ev["kind"] == "hold":
            verdicts["HOLD"] += 1
        else:
            gd = ev.get("guardian_decision")
            if gd in verdicts:
                verdicts[gd] += 1
            st = ev.get("final_status")
            if st in outcomes:
                outcomes[st] += 1

    return {
        "state_dir": str(state_dir),
        "trader_provider": _extract_provider(trader_entries, "trader"),
        "guardian_provider": _extract_provider(guardian_entries, "guardian"),
        "chains": {
            "trader": trader_chain,
            "guardian": guardian_chain,
            "all_valid": bool(trader_chain["valid"] and guardian_chain["valid"]),
        },
        "counts": {
            "total_events": len(events),
            "verdicts": verdicts,
            "outcomes": outcomes,
            "theory_snapshots": len(theories),
        },
        "theories": theories,
        "journals": _safe_journals(state_dir),
    }


def make_handler(state_dir, html_path):
    state_dir = Path(state_dir)
    html_path = Path(html_path)

    class AuditHandler(BaseHTTPRequestHandler):
        def _send_json(self, payload, status=200):
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlparse(self.path).path
            if route in {"/", "/index.html"}:
                content = html_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
                return
            if route == "/api/overview":
                self._send_json(collect_overview(state_dir))
                return
            if route == "/api/events":
                self._send_json({"events": collect_events(state_dir)})
                return
            if route == "/api/portfolio":
                self._send_json(collect_portfolio(state_dir))
                return
            self._send_json({"error": "not_found"}, status=404)

        def log_message(self, format, *args):
            return

    return AuditHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Loopback bind host (127.0.0.1 only)")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default 8765)")
    parser.add_argument("--state-dir", default=".state", help="Agent state directory containing real .jsonl logs")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("SOC Dashboard must bind strictly to a loopback host (127.0.0.1)")
    html_path = Path(__file__).resolve().parent / "audit_dashboard.html"
    handler = make_handler(args.state_dir, html_path)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Live SOC Audit Console at http://{args.host}:{args.port} (state={args.state_dir}, zero-key read-only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSOC Audit Console stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
