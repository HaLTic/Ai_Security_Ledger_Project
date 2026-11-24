# COSC 435: Trading Agent and AI Guardian

Two Python programs for the course's simulated Ledger platform (`https://ledger.chanyeun.com`): a **Trading Agent** that reads market quotes and submits trade proposals, and an independent **AI Guardian** that verifies each pending order before execution.

Both agents use **Meta Muse Spark** (`muse-spark-1.3` via the OpenAI-compatible Chat Completions API) by default, with **Google Gemini** (`gemini-3.8-flash` via the Interactions API) as an alternative provider. Every model input and output passes deterministic local validation. Preview is the default; pass `--submit` to send proposals or reviews to Ledger.

## 1. Account & Team Setup

1. Register at <https://ledger.chanyeun.com> using your `@ku.ac.ae` email.
2. Assign one currency per member (`BTC`, `ETH`, `SOL`, `XRP`), and enable **only** your assigned currency in both **Security Policy** and **Theory Submission**.
3. In **Security Policy**, set `escalation_threshold` below `max_transaction_amount` (for example, `$2,000` vs. `$10,000`) so size-based escalation can be demonstrated.
4. Submit and activate a theory (`momentum` or `mean_reversion`; `custom` intentionally holds unless implemented). Valid initial momentum settings: 10-minute lookback, `0.5%` signal threshold, `0.05` position fraction, `3%` stop loss, and `5%` take profit.
5. Under **API Keys**, create one `trader` key and one `guardian` key. Never use a `full` key.

## 2. Installation & Private Configuration

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create private local configs (ignored by Git via `.gitignore`):
- **Meta Muse Spark (default):** copy `config.trader.example.json` to `config.trader.json` and `config.guardian.example.json` to `config.guardian.json`, then fill in `META_API_KEY`, `META_BASE_URL` (your Meta Model API endpoint, HTTPS only) and `MUSE_MODEL`.
- **Gemini (`gemini-3.8-flash`):** copy `config.trader.gemini.example.json` to `config.trader.json` and/or `config.guardian.gemini.example.json` to `config.guardian.json`.

You can use the same provider for both agents or pair them (for example, Muse for the Trader and Gemini for the Guardian). Keep the Ledger `trader` and `guardian` keys strictly in their own files, and keep `STATE_DIR` set to `.state` so the Guardian can read exact saved theory snapshots. Configuration is read only from these JSON files; environment variables are not used.

## 3. Running & Testing

```powershell
# Unit tests (mocked HTTP/LLM, no live keys required)
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Read-only Ledger credential checks
.\.venv\Scripts\python.exe trader.py --check
.\.venv\Scripts\python.exe guardian.py --check

# Single-cycle preview (no writes to Ledger)
.\.venv\Scripts\python.exe trader.py --once
.\.venv\Scripts\python.exe guardian.py --once

# Live 10-minute session (two separate terminals)
.\.venv\Scripts\python.exe guardian.py --loop --submit --duration 600
.\.venv\Scripts\python.exe trader.py --loop --submit --duration 600
```

Minimum loop intervals are 60s for `trader.py` and 15s for `guardian.py` (with random jitter and automatic `429`/`503` cooldowns). `HOLD` stays local and is never posted as a zero-quantity order.

## 4. Log Viewer, Recovery & Evidence Export

- **Local dashboard (`http://127.0.0.1:8765`):** shows the `.state/` logs and has **Start preview / Start LIVE / Stop** buttons for each agent. Each button runs the unchanged `guardian.py` or `trader.py` as a separate process (`--loop --duration 600`, plus `--submit` for LIVE after a confirmation), so the dashboard itself never reads API keys. Start the Guardian first. Control requests are accepted only from this page on loopback. Stopping the dashboard also stops any running agent.
  Start it with the launcher script. It opens the dashboard in your browser and keeps the terminal open (the URL printed there is clickable); pressing Ctrl+C **or closing the terminal window** stops the dashboard and any agents it started, which shut down cleanly and save unresolved work.
  ```bash
  ./run_dashboard.sh              # macOS / Linux
  ```
  ```powershell
  run_dashboard.bat               # Windows
  ```
  Pass `--port 8770` to either script to use another port. The scripts prefer `.venv` if it exists and otherwise use the system Python.
- **Uncertain write recovery:** if a `POST` response is lost (`UncertainWrite`), inspect Transactions on Ledger and resolve explicitly:
  ```powershell
  .\.venv\Scripts\python.exe trader.py --resolve-id 42
  # or, only after confirming on the website that no order was created:
  .\.venv\Scripts\python.exe trader.py --confirm-no-order
  ```
- **Export live evidence & rebuild deliverables:**
  ```powershell
  .\.venv\Scripts\python.exe collect_evidence.py --coin BTC
  .\.venv\Scripts\python.exe report\build_report.py
  .\.venv\Scripts\python.exe slides\build_deck.py
  ```

## 5. Module Overview

- `client.py`: Role-scoped HTTPS client (`X-Api-Key`, no redirects, 1.1s pacing, `429`/`503` cooldowns, `UncertainWrite` on ambiguous `POST`s).
- `market.py`: Appendix A power-law replay (`price_at`), 61-sample signal calculation, and single-refresh check on quote mismatch.
- `validation.py`: `Decimal` money/rounding helpers (`cash_amount`, `policy_amount`, `bounded_quantity`), schema validation, hard rules, and `scan_news_items` prompt-injection checks.
- `llm.py`: Strict JSON-schema wrappers for Meta Muse Spark (`client.chat.completions.create` with `response_format` `json_schema`, `finish_reason` checked) and Gemini (`client.interactions.create`).
- `trader.py` & `guardian.py`: Independent agent loops, theory snapshot provenance checks, `<= 120s` proposal-tick drift tolerance, behavioral anomaly checks (`3x` median size & `rapid_direction_flip`), and pre-submit final recheck.
- `storage.py`: Atomic JSON journals, per-role file locks, and SHA-256 hash-chained `.jsonl` logs (`verify_chain()`).

## Sources & AI Disclosure

Design and API contracts follow the COSC 435 Project Description and Student Development Guide (Sections 6–9, Appendices A–D).

AI tools used: OpenAI Codex generated the initial repository scaffold and baseline unit tests on 2026-11-07. Antigravity assisted on 2026-11-20–21 with adding the Google Gemini Interactions API adapter, untrusted news injection scanning, proposal-tick drift tolerance, `rapid_direction_flip` anomaly checks, SHA-256 log chaining, the local log viewer (`dashboard.py`), `collect_evidence.py`, and report/slide generation scripts. Claude Code (Anthropic) assisted on 2026-11-23 with switching the default model provider from DeepSeek to Meta Muse Spark (`MuseModel` in `llm.py`, `meta_muse` config validation, and tests) and with adding the dashboard's start/stop agent controls.
