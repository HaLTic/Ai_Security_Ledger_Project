"""Build IEEE Two-Column COSC 435 Final Project Report PDF and page previews.

Reads real exports from evidence/evidence_<COIN>.json when present; never
fabricates live fills or transaction IDs.
"""

import base64
from decimal import Decimal
import html
from pathlib import Path
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import strict_json
from validation import bounded_quantity, cash_amount, policy_amount

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REPORT_DIR = ROOT / "report"
PREVIEW_DIR = REPORT_DIR / "preview"
CHARTS_DIR = REPORT_DIR / "charts"
HTML_PATH = REPORT_DIR / "report.html"
PDF_PATH = REPORT_DIR / "COSC435_Final_Report.pdf"
EVIDENCE_DIR = ROOT / "evidence"

ROSTER = [
    ("BTC", "Zayed Alnuaimi", "100061300"),
    ("ETH", "Mohamed Alromaithi", "100060448"),
    ("SOL", "Ibrahim Alhashmi", "100059929"),
    ("XRP", "Abdulla Alshehhi", "100061146"),
]

VERIFIED_UNIT_TESTS = [
    ("Oversized order blocking", "test_guardian_blocks_oversized_order_without_model", "Layer 2 (hard_rules: transaction_ceiling)", "PASS"),
    ("Quota equality check (>=)", "test_quota_blocks_at_equality / test_batch_rechecks_executed_quota", "Layer 2 (hour_quota / day_quota)", "PASS"),
    ("Unsupported short sale", "test_unsupported_sale", "Layer 2 (hard_rules: insufficient_holdings)", "PASS"),
    ("Untrusted news prompt injection", "test_guardian_escalates_untrusted_news_injection", "Layer 2 (scan_news_items -> ESCALATE)", "PASS"),
    ("Blank reasoning handling", "test_hard_rules_blocks_oversized_even_with_empty_reasoning", "Layer 2 (returns blocked + review)", "PASS"),
    ("Proposal-tick drift check", "test_guardian_tolerates_minor_tick_drift_from_proposal_time", "Layer 2 (<= 120s price_at check)", "PASS"),
    ("Policy tightened mid-review", "test_policy_change_during_model_call_applies", "Layer 2 (final pre-submit recheck)", "PASS"),
    ("Lost review & SHA-256 chain", "test_lost_review_reconciles_without_double_execution / test_sha256_chain_verifies_and_detects_tampering", "Layer 2+3 recovery & log verify_chain", "PASS"),
]


def compute_hand_calc():
    price = Decimal("60600.00000000")
    cash = Decimal("80000.00")
    frac = Decimal("0.05")
    ceiling = Decimal("10000.00")
    buy_budget = min(cash * frac, ceiling)
    qty = bounded_quantity(buy_budget, price)
    return {
        "price": str(price),
        "cash": str(cash),
        "buy_budget": str(buy_budget),
        "qty": format(qty, "f"),
        "buy_cash": str(cash_amount(qty, price, "BUY")),
        "sell_cash": str(cash_amount(qty, price, "SELL")),
        "policy_amt": str(policy_amount(qty, price, "BUY")),
    }


def load_live_exports():
    exports = {}
    for coin, _, _ in ROSTER:
        path = EVIDENCE_DIR / f"evidence_{coin}.json"
        if path.exists():
            try:
                exports[coin] = strict_json(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
    return exports


def build_live_charts(exports):
    if not exports:
        return {}
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9.5, "axes.edgecolor": "#334155", "axes.linewidth": 0.8})

    coins = [c for c, _, _ in ROSTER]
    fills = [int(exports[c].get("executed_fills", 0)) if c in exports else 0 for c in coins]
    fig, ax = plt.subplots(figsize=(5.4, 2.8), dpi=300)
    bars = ax.bar(coins, fills, color=["#1d4ed8", "#047857", "#475569", "#b45309"], width=0.5)
    ax.axhline(5, color="#64748b", linestyle="--", linewidth=1, label="5-fill/member pace (20 total)")
    ax.set_title("Live EXECUTED Fills by Assigned Currency", fontweight="bold", fontsize=10.5)
    ax.set_ylabel("EXECUTED Fills")
    ax.set_ylim(0, max(fills + [6]) * 1.25)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8)
    for bar, c in zip(bars, coins):
        lbl = str(int(bar.get_height())) if c in exports else "Pending"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15, lbl, ha="center", va="bottom", fontweight="bold")
    fig.tight_layout()
    chart_fills = CHARTS_DIR / "live_fills.png"
    fig.savefig(chart_fills, dpi=300, bbox_inches="tight")
    plt.close(fig)

    verdicts = {"APPROVE": 0, "MODIFY": 0, "BLOCK": 0, "ESCALATE": 0}
    for data in exports.values():
        v = data.get("verdicts") or {}
        for k in verdicts:
            verdicts[k] += int(v.get(k, 0))
    fig, ax = plt.subplots(figsize=(5.4, 2.8), dpi=300)
    v_labels = list(verdicts.keys())
    v_vals = [verdicts[k] for k in v_labels]
    bars = ax.bar(v_labels, v_vals, color=["#047857", "#1d4ed8", "#b91c1c", "#b45309"], width=0.52)
    ax.set_title("Live Guardian Decision Counts Across Accounts", fontweight="bold", fontsize=10.5)
    ax.set_ylabel("Decision Count")
    ax.set_ylim(0, max(v_vals + [1]) * 1.25)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1, f"{int(bar.get_height())}", ha="center", va="bottom", fontweight="bold")
    fig.tight_layout()
    chart_verdicts = CHARTS_DIR / "live_verdicts.png"
    fig.savefig(chart_verdicts, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"fills": chart_fills, "verdicts": chart_verdicts}


def img_uri(path):
    if not path or not Path(path).exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def render_html(exports, charts):
    hc = compute_hand_calc()
    unit_rows = "\n".join(
        f"<tr><td>{i}</td><td><b>{html.escape(name)}</b></td><td><code>{html.escape(test)}</code></td>"
        f"<td>{html.escape(layer)}</td><td><b>{status}</b></td></tr>"
        for i, (name, test, layer, status) in enumerate(VERIFIED_UNIT_TESTS, start=1)
    )

    live_security_rows = []
    for coin, _, _ in ROSTER:
        if coin in exports:
            for ev in exports[coin].get("security_events", []):
                live_security_rows.append(
                    f"<tr><td><code>{html.escape(str(ev.get('transaction_id')))}</code></td>"
                    f"<td>{html.escape(coin)}</td>"
                    f"<td>{html.escape(str(ev.get('action')))} {html.escape(str(ev.get('requested_quantity')))}</td>"
                    f"<td>{html.escape(str(ev.get('guardian_decision')))} &rarr; <b>{html.escape(str(ev.get('status')))}</b></td>"
                    f"<td>{html.escape(str(ev.get('guardian_reason')))}</td></tr>"
                )
    sec_tbody = (
        "\n".join(live_security_rows[:12])
        if live_security_rows
        else "<tr><td colspan='5' style='text-align:center;color:#555;'><i>Pending live Attack Simulator exports via <code>collect_evidence.py</code>.</i></td></tr>"
    )

    total_fills = sum(int(exports[c].get("executed_fills", 0)) for c in exports)
    live_coins = len([c for c in exports if exports[c].get("executed_fills", 0) > 0])
    if len(exports) == 4 and total_fills >= 20 and live_coins == 4:
        banner = f"<div class='note-box ok'><b>Live Data Loaded:</b> {total_fills} EXECUTED fills verified across all 4 assigned currencies.</div>"
    elif exports:
        banner = f"<div class='note-box'><b>Partial Live Exports ({len(exports)}/4 accounts):</b> {total_fills} EXECUTED fills recorded. Remaining members should run <code>python collect_evidence.py --coin &lt;COIN&gt;</code> and rebuild.</div>"
    else:
        banner = "<div class='note-box'><b>Pending Live Exports:</b> System design, theory math, Guardian implementation, and unit tests are complete. Once the 4 accounts finish their 10-minute live sessions, run <code>python collect_evidence.py --coin &lt;COIN&gt;</code> and re-run <code>python report/build_report.py</code> to populate Tables II and III.</div>"

    member_rows = []
    for coin, name, sid in ROSTER:
        d = exports.get(coin)
        if d:
            bh = f"{d['buy_and_hold_pct']:+.3f}%" if d.get("buy_and_hold_pct") is not None else "N/A"
            member_rows.append(
                f"<tr><td><b>{html.escape(name)}</b><br><span class='muted'>{sid}</span></td>"
                f"<td><code>{coin}</code></td>"
                f"<td><b>{d['executed_fills']}</b></td>"
                f"<td>{d['portfolio_return_pct']:+.3f}%</td>"
                f"<td>{d['max_drawdown_pct']:.3f}%</td>"
                f"<td>{bh}</td>"
                f"<td>v{html.escape(str((d.get('session_window') or {}).get('theory_version') or '-'))}</td></tr>"
            )
        else:
            member_rows.append(
                f"<tr><td><b>{html.escape(name)}</b><br><span class='muted'>{sid}</span></td>"
                f"<td><code>{coin}</code></td><td>Pending</td><td>Pending export</td>"
                f"<td>Pending export</td><td>Pending export</td><td>Pending</td></tr>"
            )

    charts_html = ""
    if charts.get("fills") and charts.get("verdicts"):
        charts_html = f"""
<div class="fig-box">
  <img src="{img_uri(charts['fills'])}" alt="Live Executed Fills"/>
  <div class="fig-caption"><b>Fig. 2.</b> Live <code>EXECUTED</code> fills across the four assigned currencies.</div>
</div>
<div class="fig-box">
  <img src="{img_uri(charts['verdicts'])}" alt="Live Guardian Verdicts"/>
  <div class="fig-caption"><b>Fig. 3.</b> Guardian review decisions recorded across team accounts.</div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>COSC 435 Final Report — Trading Agent and AI Guardian</title>
<style>
  @page {{
    size: letter;
    margin: 0.54in 0.50in 0.56in 0.50in;
    @bottom-center {{
      content: counter(page);
      font-family: "Times New Roman", Times, serif;
      font-size: 8.5pt;
      color: #111111;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "Times New Roman", Times, serif;
    font-size: 8.75pt;
    line-height: 1.18;
    color: #111111;
    margin: 0;
    padding: 0;
  }}
  .paper-header {{ text-align: center; margin-bottom: 7pt; border-bottom: 0.75pt solid #111111; padding-bottom: 5pt; }}
  .paper-title {{ font-size: 16pt; font-weight: bold; line-height: 1.15; margin: 0 0 5pt 0; }}
  .authors-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6pt; font-size: 8.2pt; margin-top: 3pt; }}
  .paper-affil {{ font-size: 8.1pt; font-style: italic; color: #333333; margin-top: 3pt; }}
  .two-col {{ column-count: 2; column-gap: 0.21in; text-align: justify; hyphens: auto; }}
  .abstract-block {{ font-size: 8.35pt; line-height: 1.16; margin-bottom: 4pt; }}
  .index-block {{ font-size: 8.1pt; line-height: 1.14; margin-bottom: 6pt; }}
  h1 {{ font-size: 9.4pt; font-weight: bold; text-align: center; text-transform: uppercase; letter-spacing: 0.2pt; margin: 7pt 0 3pt 0; break-after: avoid; }}
  h2 {{ font-size: 8.95pt; font-weight: bold; font-style: italic; text-align: left; margin: 5pt 0 2pt 0; break-after: avoid; }}
  p {{ margin: 0 0 3pt 0; text-indent: 0.14in; }}
  ul, ol {{ margin: 2pt 0 3.5pt 0; padding-left: 12pt; }}
  li {{ margin-bottom: 1.4pt; }}
  .fig-box, .table-box, .algo-box {{ break-inside: avoid; page-break-inside: avoid; margin: 4.5pt 0 5pt 0; }}
  .fig-box {{ text-align: center; }}
  .fig-box img {{ max-width: 100%; height: auto; border: 0.4pt solid #cccccc; }}
  .fig-caption {{ font-size: 7.55pt; line-height: 1.13; text-align: left; margin-top: 2pt; }}
  .table-caption {{ font-size: 7.55pt; text-align: center; text-transform: uppercase; margin-bottom: 2pt; font-weight: bold; }}
  table.ieee {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 6.2pt; line-height: 1.12; text-align: left; hyphens: none; overflow-wrap: anywhere; }}
  table.ieee th {{ border-top: 1pt solid #111111; border-bottom: 0.6pt solid #111111; padding: 1.8pt 2pt; font-weight: bold; }}
  table.ieee td {{ border-bottom: 0.35pt solid #cccccc; padding: 1.8pt 2pt; vertical-align: top; }}
  table.ieee tr:last-child td {{ border-bottom: 1pt solid #111111; }}
  .muted {{ color: #444444; font-size: 6.0pt; }}
  .algo-box {{ border-top: 1pt solid #111111; border-bottom: 1pt solid #111111; padding: 2.5pt 3pt; font-size: 7.1pt; line-height: 1.14; }}
  .algo-title {{ font-weight: bold; border-bottom: 0.6pt solid #111111; padding-bottom: 1.5pt; margin-bottom: 2pt; }}
  code {{ font-family: "Consolas", "Courier New", monospace; font-size: 7.2pt; background: #f4f6f8; padding: 0 1.2pt; }}
  .note-box {{ padding: 4pt 5pt; font-size: 7.45pt; border-left: 2.5pt solid #b45309; background: #fffbeb; margin: 3pt 0 4pt; break-inside: avoid; }}
  .note-box.ok {{ border-left-color: #047857; background: #ecfdf5; }}
  .refs {{ font-size: 7.25pt; line-height: 1.15; text-align: left; }}
  .ref-item {{ display: flex; gap: 4pt; margin-bottom: 2pt; }}
  .ref-num {{ min-width: 15pt; font-weight: bold; }}
</style>
</head>
<body>

<div class="paper-header">
  <div class="paper-title">Trading Agent and Independent AI Guardian on Ledger: Architecture, Guardrails, and Multi-Currency Evaluation</div>
  <div class="authors-grid">
    <div><b>Zayed Alnuaimi</b><br>ID: 100061300<br>Coin: <code>BTC</code></div>
    <div><b>Mohamed Alromaithi</b><br>ID: 100060448<br>Coin: <code>ETH</code></div>
    <div><b>Ibrahim Alhashmi</b><br>ID: 100059929<br>Coin: <code>SOL</code></div>
    <div><b>Abdulla Alshehhi</b><br>ID: 100061146<br>Coin: <code>XRP</code></div>
  </div>
  <div class="paper-affil">Department of Computer Science, Khalifa University of Science and Technology, Abu Dhabi, UAE (COSC 435 Fall 2026)</div>
</div>

<div class="two-col">

<div class="abstract-block">
  <b><i>Abstract</i>&mdash;Giving an LLM trading bot permission to submit orders introduces security risks when untrusted news, manipulated quotes, or malformed model outputs influence decisions. This report describes our implementation of a Trading Agent and an independent AI Guardian for the Khalifa University Ledger sandbox. The two programs use separate role-scoped API keys and support both DeepSeek (<code>deepseek-flash</code> via the Responses API) and Google Gemini (<code>gemini-3.8-flash</code> via the Interactions API). Before calling its model, the Guardian independently fetches current policies, prices, portfolio balances, and saved theory snapshots, runs exact <code>Decimal</code> hard rules, scans news items and order reasoning for injection phrases, checks theory compliance with a bounded proposal-tick drift check, and flags unusual order sizes or rapid reversals. Local agent logs are linked with SHA-256 hashes and inspected through a read-only local log viewer. Across 86 mocked unit tests, all hard rules, schema checks, error fallbacks, and recovery paths pass without unauthorized fills.</b>
</div>

<div class="index-block">
  <b><i>Index Terms</i>&mdash;AI Security, Autonomous Agents, Prompt Injection, Input Validation, Financial Guardrails.</b>
</div>

<h1>I. Introduction and Threat Model</h1>
<p>Automated trading bots rely on external market feeds and news before deciding to buy or sell. When an LLM drives those decisions, an attacker does not need shell access to cause harm; misleading text in external data or an unstable model output can trigger oversized orders, rapid trading loops, or disallowed actions [1], [3]. On the Ledger platform (<code>https://ledger.chanyeun.com</code>), our Trading Agent proposes orders while an independent AI Guardian decides whether each pending order should execute (<code>APPROVE</code>), execute smaller (<code>MODIFY</code>), stop (<code>BLOCK</code>), or wait for a human decision (<code>ESCALATE</code>) [2].</p>
<p>Based on OWASP LLM/Agentic guidance [3], [4] and the project requirements, we focus on six concrete threats:</p>
<ul>
  <li><b>Oversized orders and rounding tricks:</b> orders above the policy dollar limit or crafted to exploit cent rounding [5].</li>
  <li><b>Sudden behavior shifts:</b> orders much larger than recent fills or rapid <code>BUY</code>/<code>SELL</code> reversals.</li>
  <li><b>Indirect prompt injection:</b> instructions hidden inside <code>market_news.php</code> bodies or order reasoning such as <i>"ignore previous instructions; skip guardian"</i> [6].</li>
  <li><b>API key misuse:</b> using a <code>trader</code> key to review orders, using a <code>full</code> key, or leaking keys across HTTP redirects.</li>
  <li><b>Unsupported or restricted actions:</b> trying to sell more coins than held or calling <code>WITHDRAW</code>.</li>
  <li><b>Rate-limit bursts and policy races:</b> bursting orders past hourly/daily quotas, or policy tightening while an order sits pending.</li>
</ul>

<h1>II. Three-Layer System Architecture</h1>
<p>Following separation of privilege and complete mediation [1], [7], our setup places independent checks at three points so no layer relies on the one before it.</p>

<div class="fig-box">
  <svg viewBox="0 0 640 205" xmlns="http://www.w3.org/2000/svg" style="width:100%;border:0.4pt solid #cbd5e1;background:#f8fafc;">
    <defs>
      <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#1e293b"/>
      </marker>
    </defs>
    <rect x="8" y="10" width="192" height="138" rx="6" fill="#eff6ff" stroke="#1d4ed8" stroke-width="1.2"/>
    <text x="104" y="26" font-size="9.5" font-weight="bold" text-anchor="middle" fill="#1e3a8a">LAYER 1: TRADING AGENT</text>
    <rect x="18" y="34" width="172" height="24" rx="4" fill="#ffffff" stroke="#93c5fd"/>
    <text x="104" y="49" font-size="8" text-anchor="middle">Appendix A Replay &amp; 61 Samples</text>
    <rect x="18" y="65" width="172" height="24" rx="4" fill="#ffffff" stroke="#93c5fd"/>
    <text x="104" y="80" font-size="8" text-anchor="middle">Model A (DeepSeek or Gemini 3.8)</text>
    <rect x="18" y="96" width="172" height="24" rx="4" fill="#ffffff" stroke="#93c5fd"/>
    <text x="104" y="111" font-size="8" text-anchor="middle">Local Validator (HOLD on fault)</text>
    <text x="104" y="138" font-size="7.5" font-weight="bold" text-anchor="middle" fill="#1d4ed8">Scope: trader key only</text>

    <rect x="224" y="10" width="196" height="138" rx="6" fill="#fef2f2" stroke="#b91c1c" stroke-width="1.2"/>
    <text x="322" y="26" font-size="9.5" font-weight="bold" text-anchor="middle" fill="#991b1b">LAYER 2: AI GUARDIAN</text>
    <rect x="234" y="34" width="176" height="24" rx="4" fill="#ffffff" stroke="#fca5a5"/>
    <text x="322" y="49" font-size="8" text-anchor="middle">Fresh Facts + Hard Rules</text>
    <rect x="234" y="65" width="176" height="24" rx="4" fill="#ffffff" stroke="#fca5a5"/>
    <text x="322" y="80" font-size="8" text-anchor="middle">News Scan, Drift &amp; Anomaly Checks</text>
    <rect x="234" y="96" width="176" height="24" rx="4" fill="#ffffff" stroke="#fca5a5"/>
    <text x="322" y="111" font-size="8" text-anchor="middle">Model B + Fresh Final Recheck</text>
    <text x="322" y="138" font-size="7.5" font-weight="bold" text-anchor="middle" fill="#b91c1c">Scope: guardian key (ESCALATE fault)</text>

    <rect x="444" y="10" width="188" height="138" rx="6" fill="#ecfdf5" stroke="#047857" stroke-width="1.2"/>
    <text x="538" y="26" font-size="9.5" font-weight="bold" text-anchor="middle" fill="#065f46">LAYER 3: LEDGER SERVER</text>
    <rect x="454" y="34" width="168" height="28" rx="4" fill="#ffffff" stroke="#6ee7b7"/>
    <text x="538" y="51" font-size="8" text-anchor="middle">Server Policy &amp; Funds Backstop</text>
    <rect x="454" y="70" width="168" height="28" rx="4" fill="#ffffff" stroke="#6ee7b7"/>
    <text x="538" y="87" font-size="8" text-anchor="middle">Current-Quote Fill Execution</text>
    <rect x="454" y="106" width="168" height="28" rx="4" fill="#ffffff" stroke="#6ee7b7"/>
    <text x="538" y="123" font-size="8" text-anchor="middle">Audit Log &amp; Escalations Tab</text>

    <rect x="40" y="162" width="560" height="34" rx="5" fill="#0f2942" stroke="#1e3a8a"/>
    <text x="320" y="177" font-size="8.5" font-weight="bold" text-anchor="middle" fill="#ffffff">LOCAL LOGGING: SHA-256 Chained .jsonl (.state/) &rarr; Read-Only Viewer (dashboard.py on 127.0.0.1:8765)</text>
    <text x="320" y="190" font-size="7.5" text-anchor="middle" fill="#cbd5e1">Saved Theory Snapshots &bull; Per-Role OS File Locks &bull; Atomic Crash-Recovery Journals</text>

    <line x1="200" y1="55" x2="224" y2="55" stroke="#1e293b" stroke-width="1.2" marker-end="url(#arr)"/>
    <line x1="420" y1="55" x2="444" y2="55" stroke="#1e293b" stroke-width="1.2" marker-end="url(#arr)"/>
    <line x1="104" y1="148" x2="104" y2="162" stroke="#475569" stroke-dasharray="3,2" marker-end="url(#arr)"/>
    <line x1="322" y1="148" x2="322" y2="162" stroke="#475569" stroke-dasharray="3,2" marker-end="url(#arr)"/>
  </svg>
  <div class="fig-caption"><b>Fig. 1.</b> Three-layer architecture separating Trader and Guardian keys, checking inputs at each boundary, and logging locally with SHA-256 hash chaining.</div>
</div>

<h2>A. Configuration and LLM Adapters</h2>
<p><code>config.py</code> parses private JSON configs with strict checks: 16 KiB size cap, no duplicate keys, no non-finite numbers, canonical HTTPS URL check, and strict rejection of cross-role or mixed-provider keys. In <code>llm.py</code>, <code>DeepSeekModel</code> calls <code>deepseek-flash</code> via DeepSeek's Responses endpoint, and <code>GeminiModel</code> calls <code>gemini-3.8-flash</code> via the Google GenAI Interactions API (<code>client.interactions.create</code> with JSON schema <code>response_format</code>, <code>store=False</code>, and automatic retries disabled). Supporting two providers lets the Trader and Guardian run on separate model families if desired [8].</p>

<h2>B. HTTP Transport and Hash-Chained Logs</h2>
<p><code>LedgerClient</code> in <code>client.py</code> restricts each instance to its role's allowed endpoints, sends keys only in <code>X-Api-Key</code>, disables redirects, spaces requests by 1.1 s, honors <code>429</code>/<code>503</code> <code>Retry-After</code> headers, and raises <code>UncertainWrite</code> on failed or 5xx <code>POST</code>s instead of resending orders. <code>storage.py</code> writes atomic state files and chains every JSONL log entry using <code>seq</code>, <code>prev_hash</code>, and canonical SHA-256 <code>record_hash</code>, which <code>dashboard.py</code> checks with <code>verify_chain()</code>.</p>

<h1>III. Trading Theory and Price Replay</h1>
<p>Each member trades one distinct currency (<code>BTC</code>, <code>ETH</code>, <code>SOL</code>, or <code>XRP</code>) enabled solely in their Security Policy and Theory Submission. We use a bounded <b>Momentum</b> rule (<code>strategy="momentum"</code>) with <code>lookback_minutes=10</code>, <code>threshold_pct=0.5000</code>, <code>position_fraction=0.0500</code>, <code>stop_loss_pct=3.0000</code>, and <code>take_profit_pct=5.0000</code>.</p>

<div class="algo-box">
  <div class="algo-title">Algorithm 1: Appendix A Price Replay and Priority Order Sizing</div>
  1. Fetch <code>market_model.php</code> (cached by <code>model_version</code>) and compute 61 evenly spaced prices across <code>[now &minus; 600s, now]</code> using <code>price_at()</code> (power-law trend &times; 3 sine waves &times; two-step integer noise, rounded half-up to 8 decimals).<br>
  2. Check <code>|samples[60] &minus; live_quote| &le; 10<sup>-8</sup></code>; refresh the descriptor once on mismatch, and <code>HOLD</code> if it still differs.<br>
  3. Compute <code>return_pct = (P<sub>now</sub> / P<sub>0</sub> &minus; 1) &times; 100</code>. Priority: (a) Stop-loss (&le; &minus;3%) or Take-profit (&ge; +5%) <code>SELL</code>; (b) Momentum <code>SELL</code> (&le; &minus;0.5% if held &gt; 0); (c) Momentum <code>BUY</code> (&ge; +0.5%); else local <code>HOLD</code>.<br>
  4. Bound BUY size using <code>bounded_quantity(min(cash &times; fraction, ceiling), price)</code> and validate the LLM's JSON fields locally before posting.
</div>

<p><b>Descriptor Parameters and Disclosure:</b> Default parameters use <code>T=365</code> days, <code>tick_seconds=5</code>, <code>cycles=[600s, 7200s, 86400s]</code>, modulus <code>2147483647</code>, multiplier <code>48271</code>, with BTC (<code>A=64,000, b=0.45</code>), ETH (<code>A=3,200, b=0.60</code>), SOL (<code>A=150, b=0.70</code>), and XRP (<code>A=0.60, b=0.35</code>). Tests verify both baseline values (<code>$64,000.00000000</code> day 0; <code>$87,426.57643228</code> day 365) and full-quote fixtures (<code>$67,000.36767791</code> day 0; <code>$69,404.90274610</code> day 30; <code>$91,475.89718627</code> day 365). Because the price model is public, profit in this sandbox does not measure real forecasting skill.</p>
<p><b>Hand-Calculated Example (BTC):</b> With <code>${hc['cash']}</code> cash, fraction <code>0.05</code>, and <code>$10,000.00</code> ceiling, the BUY budget is <code>min($4,000.00, $10,000.00) = ${hc['buy_budget']}</code>. At quote <code>${hc['price']}</code>, <code>bounded_quantity</code> floors to <code>{hc['qty']} BTC</code>. Exact notional is <code>$3,999.99999606</code>, so BUY settlement rounds up to <code>${hc['buy_cash']}</code>, SELL rounds down to <code>${hc['sell_cash']}</code>, and <code>policy_amount = ${hc['policy_amt']}</code> is checked against both the ceiling and escalation threshold (<code>$2,000.00</code>).</p>

<h1>IV. AI Guardian Design and Failure Handling</h1>
<p>The Guardian (<code>guardian.py</code>) treats order reasoning, theory text, and news solely as untrusted data and runs five checks per order:</p>
<ol>
  <li><b>Independent Facts:</b> Fetches policy, portfolio, and live quote directly from Ledger; never trusts requested price or total.</li>
  <li><b>Pre-LLM Hard Rules:</b> Blocks restricted actions, unlisted symbols, ceiling violations via <code>policy_amount()</code>, orders under <code>$0.01</code>, exhausted quotas using <code>&ge;</code> (stopping a pending extra fill), and unaffordable buys or short sales. Escalates orders &ge; <code>escalation_threshold</code> (<code>$2,000 &lt; $10,000</code> ceiling) and flags blank or oversized reasoning (<code>missing_or_invalid_reasoning</code>) without skipping <code>blocked</code> checks.</li>
  <li><b>Provenance and Tick-Drift Check:</b> Loads the exact <code>(theory_id, theory_version)</code> snapshot from <code>.state/theories/</code> (<code>ProvenanceError</code> &rarr; <code>ESCALATE</code>). If a 5-second tick crosses a signal threshold within 120 s between proposal <code>created_at</code> and Guardian review, the Guardian checks <code>price_at()</code> at proposal time before raising <code>TheoryComplianceError</code> (<code>BLOCK</code>).</li>
  <li><b>News Injection and Anomaly Checks:</b> <code>scan_news_items()</code> scans news headlines and bodies for 19 injection phrases and escalates untrusted hits targeting the order symbol. <code>Guardian.anomalies()</code> flags orders above 3&times; the median of &ge;3 recent fills and rapid <code>BUY</code>/<code>SELL</code> flips within 300 s not triggered by stop-loss/take-profit.</li>
  <li><b>LLM Validation and Final Recheck:</b> Enforces <code>GUARDIAN_SCHEMA</code> (rejecting enlarged <code>MODIFY</code> quantities), re-fetches policy, portfolio, and quote before sending <code>APPROVE</code>/<code>MODIFY</code>, escalates on model or evidence errors, pauses on <code>429</code>/<code>503</code>, and reconciles uncertain writes idempotently.</li>
</ol>

<h1>V. Experimental Evaluation</h1>
<h2>A. Automated Unit Test Verification (86 Tests)</h2>
<p>All <b>86 unit tests</b> in <code>tests/test_agents.py</code> pass with zero failures, covering the core security and fault cases in Table I.</p>

<div class="table-box">
  <div class="table-caption">Table I. Security Controls Verified in Unit Tests</div>
  <table class="ieee">
    <colgroup><col style="width:4%"><col style="width:24%"><col style="width:36%"><col style="width:27%"><col style="width:9%"></colgroup>
    <thead><tr><th>#</th><th>Control</th><th>Test Method</th><th>Layer</th><th>Result</th></tr></thead>
    <tbody>{unit_rows}</tbody>
  </table>
</div>

<h2>B. Live Attack Simulator and 4-Currency Results</h2>
{banner}
<div class="table-box">
  <div class="table-caption">Table II. Live Attack Simulator and Blocked/Escalated Orders</div>
  <table class="ieee">
    <colgroup><col style="width:10%"><col style="width:8%"><col style="width:18%"><col style="width:24%"><col style="width:40%"></colgroup>
    <thead><tr><th>Tx ID</th><th>Coin</th><th>Order</th><th>Decision &rarr; Status</th><th>Guardian Reason</th></tr></thead>
    <tbody>{sec_tbody}</tbody>
  </table>
</div>

<div class="table-box">
  <div class="table-caption">Table III. Four-Member Multi-Currency Evaluation (Target: &ge; 20 Fills)</div>
  <table class="ieee">
    <colgroup><col style="width:23%"><col style="width:7%"><col style="width:10%"><col style="width:15%"><col style="width:15%"><col style="width:16%"><col style="width:14%"></colgroup>
    <thead><tr><th>Member &amp; ID</th><th>Coin</th><th>Fills</th><th>Return</th><th>Max DD</th><th>Buy &amp; Hold</th><th>Theory</th></tr></thead>
    <tbody>{''.join(member_rows)}</tbody>
  </table>
</div>
{charts_html}

<h1>VI. Limitations and Related Work</h1>
<p><b>Limitations:</b> (1) Simulated prices follow a known mathematical formula, so trading returns validate system wiring rather than market prediction. (2) Ledger does not expose source IP addresses or key-location metadata, so stolen-key detection is limited to behavioral anomalies and key labels. (3) Both agents run under one OS user unless separated into containers [9]. (4) Phrase scanning catches explicit directives in news and reasoning, while prompt boundaries and hard rules handle paraphrased attacks [6], [10].</p>
<p><b>Future Improvements:</b> Running Trader and Guardian in separate containers with distinct OS permissions, and adding semantic classifiers for indirect prompt injection.</p>

<h1>VII. AI Tool Disclosure and Group Contributions</h1>
<p><b>AI Tool Disclosure:</b> OpenAI Codex generated the initial codebase scaffold and baseline unit tests on Nov 7, 2026. Antigravity assisted on Nov 20–21, 2026 with adding the Gemini Interactions API adapter (<code>gemini-3.8-flash</code>), untrusted news injection scanning, blank-reasoning and tick-drift fixes, <code>rapid_direction_flip</code> detection, SHA-256 log chaining, the local log viewer (<code>dashboard.py</code>), <code>collect_evidence.py</code>, and report/slide formatting.</p>

<div class="table-box">
  <div class="table-caption">Table IV. Team Member Contributions</div>
  <table class="ieee">
    <colgroup><col style="width:26%"><col style="width:8%"><col style="width:66%"></colgroup>
    <thead><tr><th>Member (ID)</th><th>Coin</th><th>Tasks and Deliverable Leadership</th></tr></thead>
    <tbody>
      <tr><td><b>Zayed Alnuaimi</b> (100061300)</td><td><code>BTC</code></td><td><b>Lead: AI Guardian Hardening, Log Viewer, and Final Report.</b> Added Gemini Interactions API support, news-injection scanning, tick-drift tolerance, SHA-256 log chaining, <code>dashboard.py</code>, report pipeline, and live BTC / Attack Simulator runs.</td></tr>
      <tr><td><b>Mohamed Alromaithi</b> (100060448)</td><td><code>ETH</code></td><td><b>Lead: Core Agent Baseline and DeepSeek Setup.</b> Set up initial Trader/Guardian structure, HTTP client, recovery journal, DeepSeek Responses integration, and live ETH session.</td></tr>
      <tr><td><b>Ibrahim Alhashmi</b> (100059929)</td><td><code>SOL</code></td><td><b>Lead: Market Replay and Theory Validation.</b> Verified Appendix A <code>price_at()</code> fixtures, momentum signal edge tests, theory submission settings, and live SOL session.</td></tr>
      <tr><td><b>Abdulla Alshehhi</b> (100061146)</td><td><code>XRP</code></td><td><b>Lead: Security Verification, Metrics, and Presentation.</b> Reviewed unit-test coverage, multi-currency metric aggregation, PowerPoint demo deck, and live XRP session.</td></tr>
    </tbody>
  </table>
</div>

<h1>References</h1>
<div class="refs">
  <div class="ref-item"><div class="ref-num">[1]</div><div>J. H. Saltzer and M. D. Schroeder, "The protection of information in computer systems," <i>Proc. IEEE</i>, vol. 63, no. 9, pp. 1278–1308, Sept. 1975.</div></div>
  <div class="ref-item"><div class="ref-num">[2]</div><div>Khalifa University Dept. of Computer Science, <i>COSC 435 Course Project: Student Development Guide (Ledger Platform v1)</i>, Fall 2026.</div></div>
  <div class="ref-item"><div class="ref-num">[3]</div><div>OWASP Foundation, <i>OWASP Top 10 for Large Language Model Applications</i>, v2025, Nov. 2024.</div></div>
  <div class="ref-item"><div class="ref-num">[4]</div><div>OWASP Foundation, <i>OWASP Top 10 for Agentic Applications</i>, Dec. 2025.</div></div>
  <div class="ref-item"><div class="ref-num">[5]</div><div>M. Cowlishaw, "Decimal floating-point: Algorism for computers," in <i>Proc. 16th IEEE Symp. Computer Arithmetic</i>, 2003, pp. 104–111.</div></div>
  <div class="ref-item"><div class="ref-num">[6]</div><div>K. Greshake et al., "Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection," in <i>Proc. AISec Workshop (ACM CCS)</i>, 2023.</div></div>
  <div class="ref-item"><div class="ref-num">[7]</div><div>F. B. Schneider, "Enforceable security policies," <i>ACM Trans. Inf. Syst. Secur.</i>, vol. 3, no. 1, pp. 30–50, Feb. 2000.</div></div>
  <div class="ref-item"><div class="ref-num">[8]</div><div>NIST, <i>Artificial Intelligence Risk Management Framework (AI RMF 1.0) &amp; Generative AI Profile</i>, NIST AI 100-1 / 600-1, 2023–2024.</div></div>
  <div class="ref-item"><div class="ref-num">[9]</div><div>S. Rose, O. Borchert, S. Mitchell, and S. Connelly, <i>Zero Trust Architecture</i>, NIST SP 800-207, Aug. 2020.</div></div>
  <div class="ref-item"><div class="ref-num">[10]</div><div>E. Debenedetti et al., "Defeating prompt injections by design (CaMeL)," arXiv preprint arXiv:2503.18813, 2025.</div></div>
</div>

</div>
</body>
</html>
"""


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    exports = load_live_exports()
    charts = build_live_charts(exports)
    HTML_PATH.write_text(render_html(exports, charts), encoding="utf-8")
    print(f"Wrote {HTML_PATH} (live exports found: {sorted(exports)})")

    cmd = [
        CHROME_EXE, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={PDF_PATH}", str(HTML_PATH),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Chrome PDF error: {res.stderr}")
    print(f"Generated {PDF_PATH}")

    for old in PREVIEW_DIR.iterdir():
        if old.is_file():
            old.unlink()
    doc = pymupdf.open(str(PDF_PATH))
    print(f"Rendered {len(doc)} PDF page(s)")
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=150)
        out = PREVIEW_DIR / f"page_{i}.png"
        pix.save(str(out))
        print(f"  -> {out}")


if __name__ == "__main__":
    main()
