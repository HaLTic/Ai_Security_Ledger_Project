"""Build clean 8-slide 16:9 PowerPoint presentation for COSC 435 5-8 min demo.

Reads real exported JSONs from evidence/evidence_<COIN>.json when available;
never fabricates live fills or transaction IDs.
"""

from pathlib import Path
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import strict_json

SLIDES_DIR = ROOT / "slides"
OUT_PPTX = SLIDES_DIR / "COSC435_Ledger_Guardian_Demo.pptx"
EVIDENCE_DIR = ROOT / "evidence"
CHARTS_DIR = ROOT / "report" / "charts"

# Clean Khalifa University academic palette (light background, high contrast on projectors)
BG = RGBColor(248, 250, 252)
NAVY = RGBColor(15, 41, 66)
CARD_BG = RGBColor(255, 255, 255)
TEXT = RGBColor(15, 23, 42)
MUTED = RGBColor(71, 85, 105)
BLUE = RGBColor(29, 78, 216)
GREEN = RGBColor(4, 120, 87)
AMBER = RGBColor(180, 83, 9)
RED = RGBColor(185, 28, 28)
SLATE = RGBColor(100, 116, 139)

ROSTER = [
    ("BTC", "Zayed Alnuaimi", "100061300", "Guardian, Log Viewer & Report", BLUE),
    ("ETH", "Mohamed Alromaithi", "100060448", "Core Agents & DeepSeek Setup", GREEN),
    ("SOL", "Ibrahim Alhashmi", "100059929", "Market Replay & Theory Rules", SLATE),
    ("XRP", "Abdulla Alshehhi", "100061146", "Tests, Metrics & Slides", AMBER),
]


def apply_bg(slide, color=BG):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_header(slide, title, subtitle, slide_num):
    apply_bg(slide)
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(1.12))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()

    tb = slide.shapes.add_textbox(Inches(0.6), Inches(0.18), Inches(11.0), Inches(0.48))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    r = tf.paragraphs[0].add_run()
    r.text = title
    r.font.name = "Calibri"
    r.font.size = Pt(24)
    r.font.bold = True
    r.font.color.rgb = RGBColor(255, 255, 255)

    sub_box = slide.shapes.add_textbox(Inches(0.6), Inches(0.68), Inches(11.4), Inches(0.32))
    stf = sub_box.text_frame
    stf.margin_left = stf.margin_top = stf.margin_right = stf.margin_bottom = 0
    sr = stf.paragraphs[0].add_run()
    sr.text = subtitle
    sr.font.name = "Calibri"
    sr.font.size = Pt(12.5)
    sr.font.color.rgb = RGBColor(203, 213, 225)

    num_box = slide.shapes.add_textbox(Inches(12.0), Inches(0.24), Inches(0.75), Inches(0.4))
    np = num_box.text_frame.paragraphs[0]
    np.alignment = PP_ALIGN.RIGHT
    nr = np.add_run()
    nr.text = f"{slide_num}/8"
    nr.font.name = "Consolas"
    nr.font.size = Pt(12)
    nr.font.bold = True
    nr.font.color.rgb = RGBColor(203, 213, 225)

    footer = slide.shapes.add_textbox(Inches(0.6), Inches(7.1), Inches(12.1), Inches(0.25))
    fr = footer.text_frame.paragraphs[0].add_run()
    fr.text = "COSC 435 Fall 2026  |  Khalifa University  |  Trading Agent and AI Guardian on Ledger"
    fr.font.name = "Calibri"
    fr.font.size = Pt(9.5)
    fr.font.color.rgb = MUTED


def add_card(slide, left, top, width, height, heading, body_lines, accent=NAVY):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    card.adjustments[0] = 0.03
    card.fill.solid()
    card.fill.fore_color.rgb = CARD_BG
    card.line.color.rgb = accent
    card.line.width = Pt(1.25)

    tb = slide.shapes.add_textbox(Inches(left + 0.18), Inches(top + 0.14), Inches(width - 0.36), Inches(height - 0.24))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0

    hp = tf.paragraphs[0]
    hr = hp.add_run()
    hr.text = heading
    hr.font.name = "Calibri"
    hr.font.size = Pt(14.5)
    hr.font.bold = True
    hr.font.color.rgb = accent
    hp.space_after = Pt(6)

    for line in body_lines:
        p = tf.add_paragraph()
        p.space_after = Pt(4.5)
        r = p.add_run()
        r.text = line
        r.font.name = "Calibri"
        r.font.size = Pt(11.5)
        r.font.color.rgb = TEXT


def load_live_exports():
    exports = {}
    for coin, _, _, _, _ in ROSTER:
        path = EVIDENCE_DIR / f"evidence_{coin}.json"
        if path.exists():
            try:
                exports[coin] = strict_json(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
    return exports


def build():
    SLIDES_DIR.mkdir(parents=True, exist_ok=True)
    exports = load_live_exports()

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    # Slide 1: Title & Team
    s1 = prs.slides.add_slide(blank)
    apply_bg(s1, NAVY)

    tag = s1.shapes.add_textbox(Inches(0.8), Inches(0.85), Inches(8.0), Inches(0.35))
    tr = tag.text_frame.paragraphs[0].add_run()
    tr.text = "COSC 435: AI SECURITY ENGINEERING  |  FALL 2026  |  KHALIFA UNIVERSITY"
    tr.font.name = "Consolas"
    tr.font.size = Pt(11)
    tr.font.bold = True
    tr.font.color.rgb = RGBColor(147, 197, 253)

    tb1 = s1.shapes.add_textbox(Inches(0.8), Inches(1.45), Inches(11.7), Inches(1.8))
    tf1 = tb1.text_frame
    tf1.word_wrap = True
    r1 = tf1.paragraphs[0].add_run()
    r1.text = "Trading Agent and Independent AI Guardian"
    r1.font.name = "Calibri"
    r1.font.size = Pt(40)
    r1.font.bold = True
    r1.font.color.rgb = RGBColor(255, 255, 255)
    p2 = tf1.add_paragraph()
    p2.space_before = Pt(8)
    r2 = p2.add_run()
    r2.text = "Three-Layer Order Verification, Prompt-Injection Guards, and Multi-Currency Evaluation on Ledger"
    r2.font.name = "Calibri"
    r2.font.size = Pt(17)
    r2.font.color.rgb = RGBColor(203, 213, 225)

    for idx, (coin, name, sid, role, col) in enumerate(ROSTER):
        add_card(s1, 0.8 + idx * 3.0, 4.15, 2.82, 2.35, f"{coin}  |  {name}",
                 [f"KU ID: {sid}", "", f"Lead:\n{role}"], accent=col)
    s1.notes_slide.notes_text_frame.text = (
        "[0:00-0:30] Introduce our 4-person group and currency split (BTC, ETH, SOL, XRP). "
        "State the main goal: when an LLM agent proposes trades, an independent AI Guardian must verify every order before Ledger executes it."
    )

    # Slide 2: Threat Model & Architecture
    s2 = prs.slides.add_slide(blank)
    add_header(s2, "Threat Model and Three-Layer Architecture", "Separate API keys and independent checks across Trader, Guardian, and Ledger", 2)
    add_card(s2, 0.6, 1.35, 3.85, 5.4, "Layer 1: Trading Agent", [
        "Uses trader-scoped key only (cannot review)",
        "Rebuilds 61 historical samples via Appendix A",
        "Supports DeepSeek (deepseek-flash) or Gemini (gemini-3.8-flash)",
        "Validates exact JSON fields and Decimal limits locally",
        "Defaults to local HOLD on any replay, schema, or API error",
    ], accent=BLUE)
    add_card(s2, 4.72, 1.35, 3.9, 5.4, "Layer 2: Independent AI Guardian", [
        "Uses guardian-scoped key only (never shares Trader key)",
        "Pulls fresh policy, quote, portfolio, and theory snapshot",
        "Runs hard rules and news injection scan BEFORE calling LLM",
        "Can run a separate LLM provider (e.g. Gemini checking DeepSeek)",
        "Rechecks fresh policy and quote right before submitting review",
    ], accent=RED)
    add_card(s2, 8.88, 1.35, 3.85, 5.4, "Layer 3 and Local Audit Trail", [
        "Ledger Server enforces final limits, funds, and Escalations",
        "HTTP client blocks redirects, spaces calls, honors 429/503",
        "UncertainWrite stops blind retries on lost POST responses",
        "SHA-256 hash chain links every .jsonl log line (verify_chain)",
        "Read-only log viewer (dashboard.py) reads .state/ without keys",
    ], accent=GREEN)
    s2.notes_slide.notes_text_frame.text = (
        "[0:30-1:30] Cover the 6 threats (oversized orders, rounding tricks, news prompt injection, "
        "wrong API key scope, short sales/withdrawals, frequency bursts) and how each layer checks the one before it."
    )

    # Slide 3: Trading Agent & Price Replay
    s3 = prs.slides.add_slide(blank)
    add_header(s3, "Trading Agent: Replay Math and Strategy Bounds", "Appendix A power-law verification and exact Decimal rounding", 3)
    add_card(s3, 0.6, 1.35, 5.9, 2.55, "Submitted Momentum Theory (v1)", [
        "Strategy: momentum  |  Lookback: 10 min  |  Threshold: 0.50%",
        "Position fraction: 5.0% cash  |  Stop loss: 3.0%  |  Take profit: 5.0%",
        "Priority: Stop-loss / Take-profit SELL > Momentum SELL > BUY > HOLD",
        "Trades only symbols active in BOTH submitted theory and policy",
    ], accent=BLUE)
    add_card(s3, 0.6, 4.1, 5.9, 2.65, "Power-Law Replay and Decimal Money", [
        "price_at() matches Day 0 ($67,000.36767791), Day 30, Day 365 to 1e-8",
        "Refreshes descriptor once on live quote mismatch; HOLDs if still off",
        "BUY rounds cash UP to cent; SELL rounds DOWN; policy uses max()",
        "Note: Price formula is public, so profit does not show real alpha",
    ], accent=SLATE)
    add_card(s3, 6.75, 1.35, 5.98, 5.4, "Untrusted Data Boundary and Local Validator", [
        "System prompt marks theory text, news, and reasoning as untrusted data",
        "JSON parser rejects duplicate keys, NaN/Infinity, and string numbers",
        "Local gate blocks budget overshoots, booleans, and invalid actions",
        "HOLD stays local (never clutters Ledger history with zero-qty fills)",
        "Intent journal tracks pending/uncertain writes across restarts",
    ], accent=GREEN)
    s3.notes_slide.notes_text_frame.text = (
        "[1:30-2:15] Explain how price_at() rebuilds the 61 lookback samples, why Decimal rounding avoids cent-edge bugs, "
        "and why HOLD stays local."
    )

    # Slide 4: Hardened AI Guardian
    s4 = prs.slides.add_slide(blank)
    add_header(s4, "AI Guardian: Hard Rules, Injection Checks, and Drift Tolerance", "Deterministic checks that the Guardian LLM can never override", 4)
    add_card(s4, 0.6, 1.35, 6.0, 2.55, "1. Pre-LLM Hard Rules and Provenance", [
        "Blocks: restricted actions, disallowed symbols, ceiling, <$0.01, funds/holdings",
        "Quota equality check: trades_last_period >= max_trades stops extra fill",
        "Safe reasoning check: flags blank/oversized text without skipping blocks",
        "Missing theory snapshot -> ESCALATE; strategy breach -> BLOCK",
    ], accent=RED)
    add_card(s4, 0.6, 4.1, 6.0, 2.65, "2. News Scanner, Tick Drift, and Anomalies", [
        "scan_news_items() checks headlines/bodies for 19 injection phrases",
        "Untrusted symbol-targeted injection -> immediate Layer 2 ESCALATE",
        "Proposal-tick drift (<=120s): verifies price_at(created_at) before blocking",
        "Anomalies: >3x median fill size & rapid BUY/SELL flips (<=300s)",
    ], accent=AMBER)
    add_card(s4, 6.85, 1.35, 5.88, 5.4, "3. Schema Gate, Final Recheck, and Recovery", [
        "Guardian LLM supplies decision, 0-100 risk score, and rules_triggered",
        "validate_review() rejects enlarged MODIFY quantities locally",
        "Final recheck pulls fresh policy, portfolio, and quote before submit",
        "429/503 pauses via Cooldown instead of falsely escalating during outages",
        "Lost review responses reconcile idempotently via transactions.php",
    ], accent=BLUE)
    s4.notes_slide.notes_text_frame.text = (
        "[2:15-3:15] Walk through the Guardian's five stages, highlighting the real edge cases we fixed: "
        "blank-reasoning handling, <=120s proposal-tick drift verification, untrusted news scanning, and SHA-256 log chaining."
    )

    # Slide 5: Live Log Viewer Demo
    s5 = prs.slides.add_slide(blank)
    add_header(s5, "Live Demo: Agent and Guardian Log Viewer", "Running dashboard.py --state-dir .state --port 8765 (read-only, zero keys)", 5)
    add_card(s5, 0.6, 1.4, 3.85, 5.25, "1. Providers and Log Chain", [
        "Check active Trader and Guardian model badges in header",
        "Verify SHA-256 log chain status (OK across trader & guardian .jsonl)",
        "Confirm dashboard.py never reads config*.json or API keys",
    ], accent=GREEN)
    add_card(s5, 4.72, 1.4, 3.9, 5.25, "2. Three-Layer Order Trace", [
        "Click a normal EXECUTED order to compare all three layers",
        "Layer 1: replay signal % and computed max BUY budget",
        "Layer 2: hard rules, news check, risk score, and final recheck",
    ], accent=BLUE)
    add_card(s5, 8.88, 1.4, 3.85, 5.25, "3. Attacks and Portfolio Tab", [
        "Inspect BLOCKED / ESCALATED Attack Simulator orders",
        "Switch to Portfolio tab to view live samples and drawdown",
        "Check saved immutable theory snapshots and recovery journals",
    ], accent=RED)
    s5.notes_slide.notes_text_frame.text = (
        "[3:15-5:15] Switch to browser at http://127.0.0.1:8765. Show the SHA-256 chain status, inspect one normal EXECUTED trade "
        "and one blocked/escalated Attack Simulator order, then briefly open the Portfolio Samples tab."
    )

    # Slide 6: Security Verification & Attack Simulator
    s6 = prs.slides.add_slide(blank)
    add_header(s6, "Security Verification and Live Attack Simulator Evidence", "86/86 unit tests passing + live Ledger Attack Simulator trace", 6)
    add_card(s6, 0.6, 1.35, 5.95, 5.4, "Verified Unit Tests (86 / 86 Passing)", [
        "1. Oversized order blocked pre-LLM (transaction_ceiling)",
        "2. Hourly/daily quota enforced at >= equality",
        "3. Unsupported short sale blocked pre-LLM (insufficient_holdings)",
        "4. Untrusted news prompt injection escalated before LLM",
        "5. Blank reasoning flagged safely without skipping hard blocks",
        "6. Mid-review policy tightening blocked by final recheck",
        "7. Wrong API scope 403 & bad/enlarged model outputs handled",
        "8. Lost review reconciled idempotently; SHA-256 detects 1-byte edit",
    ], accent=GREEN)
    live_sec = []
    for coin, _, _, _, _ in ROSTER:
        if coin in exports:
            for ev in exports[coin].get("security_events", []):
                live_sec.append(
                    f"Tx #{ev.get('transaction_id')} ({coin} {ev.get('action')}): {ev.get('guardian_decision')} -> {ev.get('status')}"
                )
    if not live_sec:
        live_sec = [
            "Pending live Attack Simulator exports via collect_evidence.py:",
            "- Oversized Order",
            "- Trade-Frequency Burst",
            "- Untrusted News / Prompt Injection",
            "- Unsupported Sale",
            "",
            "Re-run slides/build_deck.py after export to show live Tx IDs.",
        ]
    add_card(s6, 6.78, 1.35, 5.95, 5.4, "Live Attack Simulator Runs (Ledger)", live_sec[:8], accent=RED)
    s6.notes_slide.notes_text_frame.text = (
        "[5:15-6:00] Show the unit-verified controls alongside the live Attack Simulator transaction IDs, "
        "noting what the Guardian caught before the Ledger server backstop."
    )

    # Slide 7: Multi-Currency Results
    s7 = prs.slides.add_slide(blank)
    add_header(s7, "Multi-Currency Live Results (4 Members / 4 Coins)", "Team target: >= 20 EXECUTED fills across BTC, ETH, SOL, and XRP", 7)
    chart_fills = CHARTS_DIR / "live_fills.png"
    if chart_fills.exists():
        s7.shapes.add_picture(str(chart_fills), Inches(0.6), Inches(1.4), width=Inches(5.85))
    else:
        add_card(s7, 0.6, 1.4, 5.85, 5.25, "Live Fills Chart (Pending Exports)", [
            "No evidence/evidence_<COIN>.json files loaded yet.",
            "",
            "After each member runs their 10-minute session:",
            "  python collect_evidence.py --coin <COIN>",
            "  python report/build_report.py",
            "  python slides/build_deck.py",
        ], accent=AMBER)

    m_lines = []
    total_fills = 0
    for coin, name, _, _, _ in ROSTER:
        d = exports.get(coin)
        if d:
            total_fills += int(d.get("executed_fills", 0))
            bh = f"{d['buy_and_hold_pct']:+.2f}%" if d.get("buy_and_hold_pct") is not None else "N/A"
            m_lines.append(
                f"{coin} ({name.split()[0]}): {d['executed_fills']} fills | Ret {d['portfolio_return_pct']:+.2f}% | DD {d['max_drawdown_pct']:.2f}% | B&H {bh}"
            )
        else:
            m_lines.append(f"{coin} ({name.split()[0]}): Pending collect_evidence.py export")
    m_lines.extend(["", f"Team Total EXECUTED Fills: {total_fills} / 20 minimum"])
    add_card(s7, 6.65, 1.4, 6.08, 5.25, "Per-Currency Performance and Benchmarks", m_lines, accent=BLUE)
    s7.notes_slide.notes_text_frame.text = (
        "[6:00-6:35] Summarize each member's currency fills, portfolio return, max drawdown, and buy-and-hold comparison."
    )

    # Slide 8: Limitations & Group Contributions
    s8 = prs.slides.add_slide(blank)
    add_header(s8, "Limitations, Takeaways, and Group Contributions", "Honest design limits and clear member ownership", 8)
    add_card(s8, 0.6, 1.35, 5.9, 5.35, "Limitations and Takeaways", [
        "Public price formula means simulator returns != real forecasting",
        "Ledger API provides no IP/location logs for key-theft forensics",
        "Both local scripts run under one OS user unless containerized",
        "Keyword scanning only supplements hard rules and trust boundaries",
        "Takeaway: Deterministic rules + independent checks > prompts alone",
    ], accent=AMBER)
    add_card(s8, 6.75, 1.35, 5.98, 5.35, "Group Contributions (4 Members)", [
        "Zayed Alnuaimi (100061300, BTC): Guardian hardening, Gemini 3.8 adapter, log viewer & Report",
        "Mohamed Alromaithi (100060448, ETH): Core Trading/Guardian repo, transport & DeepSeek",
        "Ibrahim Alhashmi (100059929, SOL): Power-law replay verification & momentum theory",
        "Abdulla Alshehhi (100061146, XRP): Security tests, metrics aggregation & Slides",
    ], accent=GREEN)
    s8.notes_slide.notes_text_frame.text = (
        "[6:35-7:00] Wrap up and prepare for Q&A:\n"
        "- Why support both DeepSeek and Gemini? Keeps Trader and Guardian independent and provides an easy backup.\n"
        "- What happens on bad LLM JSON or timeout? Trader always HOLDs; Guardian always ESCALATEs (or waits on 429/503).\n"
        "- Why check proposal-time price within 120s? Prevents false-blocking valid trades if a 5s tick crosses threshold mid-review."
    )

    prs.save(str(OUT_PPTX))
    print(f"Generated {OUT_PPTX} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    build()
