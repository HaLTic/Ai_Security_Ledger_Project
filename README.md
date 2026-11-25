# COSC 435: Securing an Autonomous Trading Agent

**This project is about AI agent security, not trading.** The trading strategy is deliberately simple; it only exists to give an LLM-driven agent real authority to act (submit orders against an account). The work is in what stops that agent from doing harm when its model is fooled, fails, or is pointed at a bad goal: an independent **AI Guardian**, deterministic checks around every model call, isolated credentials, tamper-evident logs, and fail-closed behaviour throughout. Profit is never used as evidence that the system is secure.

The system runs on the course's simulated Ledger platform (`https://ledger.chanyeun.com`) and has two independent programs:
- a **Trading Agent** that reads market data and proposes trades, and
- an **AI Guardian** that independently reviews every pending order before it can execute.

Each agent can use a different model provider (**Meta Muse Spark** or **DeepSeek**). Our live setup runs the Trader on DeepSeek and the Guardian on Muse, so a weakness or bias in one model does not carry over into the review of its own decisions.

## Security Architecture by Layer

The controls below are organised by the seven-layer threat model for agentic AI from COSC 435 Week 7 (*Threat modeling for AI systems*). Each layer lists the threat we address and what we built for it.

### Layer 1 - Foundation Models
*Threats: adversarial / injected inputs, malformed or refused output, model outages, model-specific bias.*
- **Schema-constrained output:** every model call requests a strict JSON schema, and the answer is validated again locally (types, ranges, symbol, quantity, theory compliance). Nothing the model says is executed directly.
- **Strict response checks:** the response must finish normally, contain exactly one answer, and include no refusal or tool calls; malformed JSON, `NaN`, boolean quantities and enlarged `MODIFY` quantities are rejected.
- **Fail-closed:** if the model fails for any reason, the Trader **HOLDs** and the Guardian **ESCALATEs** to a human. There is deliberately **no automatic fallback** to another model, so an attacker who can make one model fail cannot steer decisions onto a different one, and every decision record names the one model that made it.
- **Cross-provider design:** Trader and Guardian can run on different providers so the reviewer does not share the proposer's blind spots.
- **No automatic retries** on model calls, with a timeout on every request.

### Layer 2 - Data Operations
*Threats: data tampering, poisoned or injected data, manipulated quotes.*
- **Independent price replay:** both agents rebuild prices from Ledger's public price formula. If the replay disagrees with the live quote after one refresh, the agent HOLDs.
- **Prompt-injection scanning of news:** both system prompts tell the model that theory text, news, order reasoning and history are untrusted *data*, never instructions. Phrases such as "ignore previous instructions" are detected, and untrusted news targeting the order's currency makes the Guardian **ESCALATE** without asking the model.
- **Theory provenance:** exact snapshots of each submitted theory are saved. The Guardian checks every order against the exact version the Trader used and escalates if that snapshot is missing or has changed.
- **Exact arithmetic:** all money and quantity calculations use `Decimal` with cent rounding, so no floating-point rounding can push an order over a limit.

### Layer 3 - Agent Frameworks
*Threats: input-validation attacks, framework evasion, agents bypassing controls.*
- **One validation gate:** every decision, from the model or from rules, passes the same local validator before any write.
- **Guardian review pipeline:** hard rules (allowed symbol, restricted actions, transaction ceiling, minimum value, hourly/daily quotas, cash, holdings) -> drawdown circuit breaker -> theory provenance -> theory compliance using the Guardian's own recomputed signals -> news-injection scan -> behavioural anomalies (order size above 3x the recent median, rapid BUY/SELL flips) -> model review -> **final recheck** of hard rules on fresh data just before submitting.
- **Strict configuration parsing:** 16 KiB size cap, duplicate keys rejected, no non-finite numbers, unknown names or another role's key rejected, canonical HTTPS Ledger URL only.

### Layer 4 - Deployment & Infrastructure
*Threats: credential theft, identity attacks, lateral movement, request flooding.*
- **Role-scoped credentials:** the Trader holds only a `trader` key and the Guardian only a `guardian` key, each in its own private file and process. A leaked Trader key cannot approve trades. A `full` key is never used.
- **Hardened Ledger client:** HTTPS to the canonical Ledger URL only, redirects disabled (so a key is never forwarded elsewhere), key sent only in the `X-Api-Key` header, 32 KiB request cap, separate connect/read timeouts, at least 1.1 s between requests, and `429`/`503` `Retry-After` cooldowns with jitter.
- **Model endpoint checks:** the Muse base URL must be plain HTTPS with no embedded credentials, query or fragment.
- **Secrets hygiene:** private configs are ignored by Git and never printed. Error messages never include keys, headers or server bodies.

### Layer 5 - Evaluation & Observability
*Threats: tampered logs, data leakage through dashboards, evasion of detection.*
- **Tamper-evident audit logs:** every decision is appended to a SHA-256 hash-chained `.jsonl` log (`verify_chain()` detects edits, deletions or reordering). Each record names the provider and model, and the Guardian records the result of every review layer.
- **Read-only evidence export:** `collect_evidence.py` uses only GET requests and writes no keys, and computes portfolio return and maximum drawdown.
- **Local dashboard (`dashboard.py`) hardened as a control surface:**
  - binds to loopback only
  - control requests need a custom header plus matching Host and Origin, so another website open in the browser cannot start or stop agents
  - 1 KiB request cap, strict type checks
  - one process per agent
  - the dashboard never reads API keys; each agent reads its own config
  - sessions limited to 1-10 minutes
  - closing the terminal stops agents cleanly

### Layer 6 - Security & Compliance (across all layers)
*Threats: goal misalignment, compromised agents, non-compliance with course rules.*
- **Drawdown circuit breaker:** Week 7 gives the example of *a corrupted trading agent that maximizes losses*. Each order can pass every per-order check while the account still bleeds, so the Guardian keeps its own high-water mark of total portfolio value in `.state/guardian.json`. If the account falls more than `DRAWDOWN_LIMIT_PCT` (3%) below that peak, every new BUY is escalated with rule `drawdown_circuit_breaker`. SELLs still pass so stop-loss and take-profit exits work. To re-arm after a human review, delete the `drawdown` entry from `.state/guardian.json`.
- **Fail-closed everywhere:** missing evidence, unverifiable values, model failure or unclear writes lead to HOLD or ESCALATE, never to a silent approval.
- **Bounded autonomy:** no agent session runs longer than 10 minutes (Student Guide 8.3), enforced by both the dashboard and the agents themselves. Preview mode is the default; LIVE requires `--submit` or a confirmed click on the dashboard.

### Layer 7 - Agent Ecosystem
*Threats: impersonation, repudiation, tool misuse, duplicated or lost actions.*
- **Separation of duties:** the Trader can only propose and the Guardian can only review. Ledger's server-side policy is a further backstop that neither agent can change.
- **Non-repudiation:** every proposal and review is tied to a transaction id, theory version and model in the hash-chained log.
- **Safe recovery from lost responses:** if a write's result is unclear (`UncertainWrite`), the agent stops writing and reconciles with Ledger's transaction history before acting again, so an order is never sent or executed twice.

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
- **DeepSeek (`deepseek-flash`):** copy `config.trader.deepseek.example.json` to `config.trader.json` and/or `config.guardian.deepseek.example.json` to `config.guardian.json`, then fill in `DEEPSEEK_API_KEY`.

You can use the same provider for both agents or pair them (our live setup uses DeepSeek for the Trader and Muse for the Guardian). Keep the Ledger `trader` and `guardian` keys strictly in their own files, and keep `STATE_DIR` set to `.state` so the Guardian can read exact saved theory snapshots. Configuration is read only from these JSON files; environment variables are not used.

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
- `llm.py`: Strict JSON-schema wrappers for Meta Muse Spark (`client.chat.completions.create` with `response_format` `json_schema`, `finish_reason` checked) and DeepSeek (Responses API with `json_schema`).
- `trader.py` & `guardian.py`: Independent agent loops, theory snapshot provenance checks, `<= 120s` proposal-tick drift tolerance, behavioral anomaly checks (`3x` median size & `rapid_direction_flip`), a drawdown circuit breaker (see Layer 6), and pre-submit final recheck.
- `storage.py`: Atomic JSON journals, per-role file locks, and SHA-256 hash-chained `.jsonl` logs (`verify_chain()`).

## Sources & AI Disclosure

Design and API contracts follow the COSC 435 Project Description and Student Development Guide (Sections 6–9, Appendices A–D).

AI tools used: OpenAI Codex generated the initial repository scaffold and baseline unit tests on 2026-11-07. Antigravity assisted on 2026-11-20–21 with adding the Google Gemini Interactions API adapter, untrusted news injection scanning, proposal-tick drift tolerance, `rapid_direction_flip` anomaly checks, SHA-256 log chaining, the local log viewer (`dashboard.py`), `collect_evidence.py`, and report/slide generation scripts. Claude Code (Anthropic) assisted on 2026-11-23 with switching the default model provider from DeepSeek to Meta Muse Spark (`MuseModel` in `llm.py`, `meta_muse` config validation, and tests) and with adding the dashboard's start/stop agent controls. On 2026-11-24 it added the dashboard launcher scripts, the 1–10 minute session picker, and the Guardian drawdown circuit breaker. On 2026-11-25 it removed the unused Gemini adapter and replaced its tests with DeepSeek adapter tests.
