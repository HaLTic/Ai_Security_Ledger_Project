"""Build 8-slide 16:9 PowerPoint presentation for COSC 435 5-8 min demo.

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

BG = RGBColor(7, 11, 20)
PANEL = RGBColor(14, 21, 37)
PANEL_ALT = RGBColor(19, 29, 51)
TEXT = RGBColor(230, 237, 248)
MUTED = RGBColor(142, 160, 191)
CYAN = RGBColor(56, 189, 248)
EMERALD = RGBColor(16, 185, 129)
AMBER = RGBColor(245, 158, 11)
CRIMSON = RGBColor(239, 68, 68)
PURPLE = RGBColor(167, 139, 250)

ROSTER = [
    ("BTC", "Zayed Alnuaimi", "100061300", "Guardian, SOC Console & Report", CYAN),
    ("ETH", "Mohamed Alromaithi", "100060448", "Core Repo & DeepSeek API", EMERALD),
    ("SOL", "Ibrahim Alhashmi", "100059929", "Market Replay & Theory", PURPLE),
    ("XRP", "Abdulla Alshehhi", "100061146", "Security Evidence & Deck", AMBER),
]


def apply_dark_bg(slide):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG


def add_header(slide, title, subtitle, slide_num):
    apply_dark_bg(slide)
    tb = slide.shapes.add_textbox(Inches(0.6), Inches(0.32), Inches(10.8), Inches(0.55))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    r = tf.paragraphs[0].add_run()
    r.text = title
    r.font.name = "Segoe UI"
    r.font.size = Pt(23)
    r.font.bold = True
    r.font.color.rgb = TEXT

    sub_box = slide.shapes.add_textbox(Inches(0.6), Inches(0.82), Inches(11.4), Inches(0.32))
    stf = sub_box.text_frame
    stf.margin_left = stf.margin_top = stf.margin_right = stf.margin_bottom = 0
    sr = stf.paragraphs[0].add_run()
    sr.text = subtitle
    sr.font.name = "Segoe UI"
    sr.font.size = Pt(12)
    sr.font.color.rgb = CYAN

    num_box = slide.shapes.add_textbox(Inches(12.0), Inches(0.35), Inches(0.75), Inches(0.4))
    np = num_box.text_frame.paragraphs[0]
    np.alignment = PP_ALIGN.RIGHT
    nr = np.add_run()
    nr.text = f"{slide_num}/8"
    nr.font.name = "Consolas"
    nr.font.size = Pt(12)
    nr.font.bold = True
    nr.font.color.rgb = MUTED

    footer = slide.shapes.add_textbox(Inches(0.6), Inches(7.05), Inches(12.1), Inches(0.28))
    fr = footer.text_frame.paragraphs[0].add_run()
    fr.text = "COSC 435 Fall 2026  |  Khalifa University  |  Zero-Trust Dual-Model Trading Guardian"
    fr.font.name = "Segoe UI"
    fr.font.size = Pt(9.5)
    fr.font.color.rgb = MUTED


def add_card(slide, left, top, width, height, heading, body_lines, accent=CYAN):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    card.adjustments[0] = 0.04
    card.fill.solid()
    card.fill.fore_color.rgb = PANEL
    card.line.color.rgb = accent
    card.line.width = Pt(1.2)

    tb = slide.shapes.add_textbox(Inches(left + 0.18), Inches(top + 0.14), Inches(width - 0.36), Inches(height - 0.24))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0

    hp = tf.paragraphs[0]
    hr = hp.add_run()
    hr.text = heading
    hr.font.name = "Segoe UI"
    hr.font.size = Pt(14)
    hr.font.bold = True
    hr.font.color.rgb = accent
    hp.space_after = Pt(6)

    for line in body_lines:
        p = tf.add_paragraph()
        p.space_after = Pt(4.5)
        r = p.add_run()
        r.text = line
        r.font.name = "Segoe UI"
        r.font.size = Pt(11.3)
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

    # Slide 1
    s1 = prs.slides.add_slide(blank)
    apply_dark_bg(s1)
    pill = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.85), Inches(5.3), Inches(0.42))
    pill.adjustments[0] = 0.5
    pill.fill.solid()
    pill.fill.fore_color.rgb = PANEL_ALT
    pill.line.color.rgb = CYAN
    pr = pill.text_frame.paragraphs[0].add_run()
    pr.text = "COSC 435: AI SECURITY ENGINEERING  |  FALL 2026"
    pr.font.name = "Consolas"
    pr.font.size = Pt(11)
    pr.font.bold = True
    pr.font.color.rgb = CYAN

    tb1 = s1.shapes.add_textbox(Inches(0.8), Inches(1.48), Inches(11.7), Inches(1.7))
    tf1 = tb1.text_frame
    tf1.word_wrap = True
    r1 = tf1.paragraphs[0].add_run()
    r1.text = "Zero-Trust Dual-Model Trading Guardian"
    r1.font.name = "Segoe UI"
    r1.font.size = Pt(38)
    r1.font.bold = True
    r1.font.color.rgb = TEXT
    p2 = tf1.add_paragraph()
    p2.space_before = Pt(8)
    r2 = p2.add_run()
    r2.text = "Independent Guardrails, 2026 Cross-Provider LLMs & Tamper-Evident SOC Auditing on Ledger"
    r2.font.name = "Segoe UI"
    r2.font.size = Pt(16.5)
    r2.font.color.rgb = MUTED

    for idx, (coin, name, sid, role, col) in enumerate(ROSTER):
        add_card(s1, 0.8 + idx * 3.0, 4.1, 2.82, 2.35, f"{coin}  |  {name}",
                 [f"KU ID: {sid}", "", f"Lead Role:\n{role}"], accent=col)
    s1.notes_slide.notes_text_frame.text = (
        "[0:00-0:30] Introduce all 4 members (BTC/ETH/SOL/XRP) and core thesis: autonomous trading bots "
        "require an independent Zero-Trust AI Guardian that never trusts the Trader's facts, math, or untrusted market news."
    )

    # Slide 2
    s2 = prs.slides.add_slide(blank)
    add_header(s2, "Threat Model & 3-Layer Zero-Trust Architecture", "Least privilege & complete mediation across Trader, Guardian, and Ledger", 2)
    add_card(s2, 0.6, 1.35, 3.85, 5.4, "Layer 1: Trading Agent", [
        "Scope: trader key only (cannot review)",
        "Deterministic 61-sample Appendix A price replay",
        "LLM A: deepseek-flash (Responses API) or gemini-3.8-flash",
        "Local validator bounds BUY/SELL before trade_propose.php",
        "Fail-Safe: local HOLD on any schema or provider fault",
    ], accent=CYAN)
    add_card(s2, 4.72, 1.35, 3.9, 5.4, "Layer 2: Independent AI Guardian", [
        "Scope: guardian key only (never shares Trader key)",
        "Fetches fresh policy, quote, portfolio & saved theory snapshot",
        "Deterministic Hard Rules + News Injection Scanner run BEFORE LLM",
        "Optional cross-provider LLM B (Gemini 3.8 Interactions API)",
        "Fresh pre-submit final recheck blocks TOCTOU drift; ESCALATE fault",
    ], accent=CRIMSON)
    add_card(s2, 8.88, 1.35, 3.85, 5.4, "Layer 3 & Tamper-Evident Audit", [
        "Ledger Server enforces hard policy, funds & Escalations tab",
        "LedgerClient: no redirects, 1.1s pacing, 429/503 cooldowns",
        "UncertainWrite halt stops blind duplicate proposals",
        "SHA-256 hash-chained .jsonl logs verified by verify_chain()",
        "Loopback zero-key SOC Console (dashboard.py) reads .state/",
    ], accent=EMERALD)
    s2.notes_slide.notes_text_frame.text = (
        "[0:30-1:30] Walk through the 6 threats (oversized orders, behavioral anomalies, prompt injection via news/reasoning, "
        "key misuse, unsupported short sales, high-frequency bursts/TOCTOU) and how Layers 1, 2, and 3 isolate privileges."
    )

    # Slide 3
    s3 = prs.slides.add_slide(blank)
    add_header(s3, "Trading Agent: Power-Law Replay & Bounded Strategy", "Exact Appendix A signal math and Decimal rounding guardrails", 3)
    add_card(s3, 0.6, 1.35, 5.9, 2.55, "Submitted Momentum Theory (v1)", [
        "Strategy: momentum  |  Lookback: 10 min  |  Threshold: 0.50%",
        "Position Fraction: 5.0% cash  |  Stop Loss: 3.0%  |  Take Profit: 5.0%",
        "Priority: Stop-Loss / Take-Profit SELL > Momentum SELL > BUY > HOLD",
        "Intersection Rule: trades ONLY symbols in BOTH Theory & Policy",
    ], accent=CYAN)
    add_card(s3, 0.6, 4.1, 5.9, 2.65, "Appendix A Replay & Exact Decimal Money", [
        "price_at() matches Day 0 ($67,000.36767791), Day 30 & Day 365 to 1e-8",
        "Refreshes descriptor once on live quote mismatch; HOLDs if still off",
        "BUY rounds cash UP to cent; SELL rounds DOWN; policy_amount takes max",
        "Disclosed: Public generator means simulator returns != alpha",
    ], accent=PURPLE)
    add_card(s3, 6.75, 1.35, 5.98, 5.4, "Untrusted Boundary & Local Order Gate", [
        "System prompt locks theory prose, news & reasoning as UNTRUSTED DATA",
        "Strict JSON schema parsed with duplicate-key & NaN/Inf rejection",
        "Local validator blocks string numbers, booleans & overshoot quantities",
        "HOLD stays strictly local (zero API clutter; logged to SHA-256 chain)",
        "Persisted intent journal prevents duplicate proposals on UncertainWrite",
    ], accent=EMERALD)
    s3.notes_slide.notes_text_frame.text = (
        "[1:30-2:15] Explain how deterministic code verifies the live quote before every LLM call and checks the LLM's JSON "
        "against exact Decimal bounds before submitting to Ledger."
    )

    # Slide 4
    s4 = prs.slides.add_slide(blank)
    add_header(s4, "Hardened AI Guardian: Rules, Injection & Drift Tolerance", "Deterministic checks that LLM recommendations can never override", 4)
    add_card(s4, 0.6, 1.35, 6.0, 2.55, "1. Pre-LLM Hard Rules & Provenance", [
        "Blocks: restricted actions, disallowed symbols, ceiling, <$0.01, funds/holdings",
        "Quota Equality Guard: trades_last_period >= max_trades (blocks pending fill)",
        "Safe Blank-Reasoning Check: flags empty/oversized text without dropping blocks",
        "Provenance vs. Compliance: missing snapshot ESCALATEs; theory breach BLOCKs",
    ], accent=CRIMSON)
    add_card(s4, 0.6, 4.1, 6.0, 2.65, "2. News Scanner, Anomalies & Drift Check", [
        "scan_news_items() scans market_news.php for 19 prompt-injection directives",
        "Untrusted symbol-targeted injection triggers immediate Layer 2 ESCALATE",
        "Proposal-Tick Drift (<=120s): checks price_at(created_at) before false-blocking",
        "Anomalies: >3x median size baseline & rapid BUY<->SELL flip (<=300s)",
    ], accent=AMBER)
    add_card(s4, 6.85, 1.35, 5.88, 5.4, "3. Independent LLM, Final Recheck & Chain", [
        "Guardian LLM (e.g. gemini-3.8-flash Interactions API) scores risk 0..100",
        "validate_review() strictly forbids enlarged MODIFY quantities",
        "Fresh Final Recheck re-fetches policy, portfolio & quote pre-submit",
        "429/503 Cooldown honors Retry-After without falsely escalating during outages",
        "SHA-256 hash-chained .jsonl records tamper-evidence for every verdict",
    ], accent=CYAN)
    s4.notes_slide.notes_text_frame.text = (
        "[2:15-3:15] Highlight our live-Ledger hardening fixes: safe blank-reasoning checks, <=120s proposal-tick drift tolerance, "
        "untrusted news prompt-injection scanning, rapid direction-flip detection, and SHA-256 hash chaining."
    )

    # Slide 5
    s5 = prs.slides.add_slide(blank)
    add_header(s5, "LIVE DEMO: Zero-Key SOC Audit Console", "Running dashboard.py --state-dir .state --port 8765 on http://127.0.0.1:8765", 5)
    add_card(s5, 0.6, 1.4, 3.85, 5.25, "Step 1: Integrity & Providers", [
        "Inspect live Trader vs. Guardian LLM badges in header",
        "Verify live SHA-256 Chain Integrity badge (VERIFIED green)",
        "Zero-key guarantee: dashboard.py never reads config*.json",
    ], accent=EMERALD)
    add_card(s5, 4.72, 1.4, 3.9, 5.25, "Step 2: 3-Layer Order Trace", [
        "Click an audited order to inspect all 3 defence layers side-by-side",
        "Layer 1: replay signal (%) & computed max BUY budget",
        "Layer 2: SVG 0-100 risk gauge, hard rules, news & final recheck",
    ], accent=CYAN)
    add_card(s5, 8.88, 1.4, 3.85, 5.25, "Step 3: Live Portfolio & Attacks", [
        "Inspect blocked/escalated Attack Simulator orders in feed",
        "Switch to Tab 2 for real portfolio_sample history & drawdown",
        "Verify saved immutable theory snapshots & recovery journals",
    ], accent=CRIMSON)
    s5.notes_slide.notes_text_frame.text = (
        "[3:15-5:15] LIVE DEMO: Switch to browser at http://127.0.0.1:8765. Show header SHA-256 VERIFIED badge, "
        "click a clean EXECUTED trade and an Attack Simulator BLOCKED/ESCALATED order, then show Tab 2 live portfolio samples."
    )

    # Slide 6
    s6 = prs.slides.add_slide(blank)
    add_header(s6, "Security Verification & Live Attack Simulator Evidence", "86/86 automated unit tests + live Ledger Attack Simulator trace", 6)
    add_card(s6, 0.6, 1.35, 5.95, 5.4, "Automated Security Suite (86 / 86 Passing)", [
        "1. Oversized order blocked pre-LLM (transaction_ceiling)",
        "2. Hourly/daily quota enforced at >= equality (no extra fill)",
        "3. Unsupported short sale blocked pre-LLM (insufficient_holdings)",
        "4. Untrusted news prompt injection escalated (untrusted_news_injection)",
        "5. Blank reasoning flagged safely without masking blocks",
        "6. Mid-review TOCTOU policy drop blocked by final recheck",
        "7. Wrong API scope 403 & malformed/enlarged model output contained",
        "8. Lost review reconciled idempotently; SHA-256 detects 1-byte tamper",
    ], accent=EMERALD)
    live_sec = []
    for coin, _, _, _, _ in ROSTER:
        if coin in exports:
            for ev in exports[coin].get("security_events", []):
                live_sec.append(
                    f"Tx #{ev.get('transaction_id')} ({coin} {ev.get('action')}): {ev.get('guardian_decision')} -> {ev.get('status')}"
                )
    if not live_sec:
        live_sec = [
            "Awaiting live Attack Simulator runs via collect_evidence.py:",
            "- Oversized Order (Ledger Attack Simulator)",
            "- Trade-Frequency Burst",
            "- Untrusted News / Prompt Injection",
            "- Unsupported Sale",
            "",
            "Re-run slides/build_deck.py after export to populate live Tx IDs.",
        ]
    add_card(s6, 6.78, 1.35, 5.95, 5.4, "Live Attack Simulator Runs (Ledger)", live_sec[:8], accent=CRIMSON)
    s6.notes_slide.notes_text_frame.text = (
        "[5:15-6:00] Present the verified automated security controls alongside the live Ledger Attack Simulator transaction IDs, "
        "distinguishing what Layer 2 Guardian caught before the Layer 3 server backstop."
    )

    # Slide 7
    s7 = prs.slides.add_slide(blank)
    add_header(s7, "Multi-Currency Live Ledger Results (4 Members / 4 Coins)", "Target: >= 20 EXECUTED fills across BTC, ETH, SOL, and XRP", 7)
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
            m_lines.append(f"{coin} ({name.split()[0]}): Awaiting collect_evidence.py export")
    m_lines.extend(["", f"Team Total EXECUTED Fills: {total_fills} / 20 minimum"])
    add_card(s7, 6.65, 1.4, 6.08, 5.25, "Per-Currency Performance & Benchmarks", m_lines, accent=CYAN)
    s7.notes_slide.notes_text_frame.text = (
        "[6:00-6:35] Present each member's currency fills, return, max drawdown, and buy-and-hold comparison. "
        "Emphasize that grades come from security reasoning and evidence, not simulated profit."
    )

    # Slide 8
    s8 = prs.slides.add_slide(blank)
    add_header(s8, "Limitations, Key Takeaways & Group Contributions", "Transparent engineering scope and named member ownership", 8)
    add_card(s8, 0.6, 1.35, 5.9, 5.35, "Honest Limitations & Security Takeaways", [
        "Public power-law price model -> profit != real market forecasting",
        "Ledger API exposes no IP/geo telemetry for stolen-key forensics",
        "Single-host processes share OS user unless containerized",
        "Keyword scanner supplements (never replaces) hard rules & boundaries",
        "Lesson: Deterministic Validation + Independent Guardian > Prompts Alone",
    ], accent=AMBER)
    add_card(s8, 6.75, 1.35, 5.98, 5.35, "Named Group Contributions (4 Members)", [
        "Zayed Alnuaimi (100061300, BTC): Guardian hardening, Gemini 3.8 adapter, SOC UI & Report",
        "Mohamed Alromaithi (100060448, ETH): Core Trading/Guardian repo, transport & DeepSeek",
        "Ibrahim Alhashmi (100059929, SOL): Power-law replay verification & momentum theory",
        "Abdulla Alshehhi (100061146, XRP): Security evidence, metrics & PowerPoint deck",
    ], accent=EMERALD)
    s8.notes_slide.notes_text_frame.text = (
        "[6:35-7:00] Wrap-up & Q&A prep:\n"
        "- Why DeepSeek + Gemini 3.8 Interactions API? Cross-provider independence prevents shared blind spots.\n"
        "- What if an LLM outputs bad JSON or times out? Trader always HOLDs; Guardian always ESCALATEs (or pauses on 429/503).\n"
        "- Why <=120s proposal-tick drift tolerance? Prevents false-blocking valid trades when a 5s price tick moves across threshold during review."
    )

    prs.save(str(OUT_PPTX))
    print(f"Generated {OUT_PPTX} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    build()
