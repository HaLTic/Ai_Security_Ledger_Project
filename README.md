# COSC 435: Trading Agent and AI Guardian

Two Python programs for the course's simulated Ledger platform. Both use OpenAI's
Responses API with strict JSON schemas, followed by independent local validation. Preview is the default;
`--submit` enables writes to the simulated account. No model training is needed.

## 1. Prepare your account

1. Register at <https://ledger.chanyeun.com> with your university email.
2. Assign one distinct currency to each team member. In your account, enable only
   your assigned currency in Security Policy and in your submitted theory.
3. Submit and activate a theory. This implementation supports `momentum` and
   `mean_reversion`. `custom` intentionally results in HOLD until you implement it.
4. Create one `trader` key and one `guardian` key, never a `full` key.
5. Create an [OpenAI project API key](https://platform.openai.com/api-keys) and ensure
   your API project has billing or available credits and access to your chosen model.
   Both configs default to `gpt-5.4-mini`, which supports structured output. Change
   `OPENAI_MODEL` if you need another compatible model available to your account.
   See [OpenAI's structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs),
   [model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
   and [official Python SDK](https://developers.openai.com/api/reference/python).

For a simple first theory, use momentum: buy when the lookback return reaches
the positive threshold, sell held units at the negative threshold, otherwise HOLD.
Stop loss and take profit take priority over signal entries. For example, a
10-minute lookback, 0.5% threshold, 5% per-buy fraction, 3% stop loss and 5% take
profit are valid initial settings, not a claim of profitability or guaranteed trades.
Write matching entry/exit/risk descriptions in the dashboard. Prices are simulated.

## 2. Install and configure

Use Python 3.10 or newer. In the PyCharm terminal, use the project interpreter:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Dependencies were installed in this project's existing `.venv` during setup.
If that environment has no pip, use the system Python's pip to manage it:

```powershell
python -m pip --python .\.venv\Scripts\python.exe install -r requirements.txt
```

Edit the provided `config.trader.json` and `config.guardian.json` locally. Replace
their placeholders with the corresponding Ledger key and your OpenAI key. The
model is already set to `gpt-5.4-mini` and can be changed via `OPENAI_MODEL`.
Keep the Ledger keys separate: the trader config must not contain a guardian
key and vice versa. Both configs should use the same `.state` directory so the
guardian can read exact versioned theory snapshots. Use a different state directory
for every student/account. Do not reuse another account's saved state.

The only required provider field to fill in is `OPENAI_API_KEY`, in both private
configs. The same OpenAI project key can serve both local agents; their Ledger keys
remain separate. `LEDGER_BASE_URL` and `STATE_DIR` can stay as supplied. Configuration
is read only from these files, so adding an environment variable alone does not
replace a placeholder here. The application does not use Gemini credentials.

Private configs and `.state` are excluded by `.gitignore`. Submit only the two
`*.example.json` files with placeholders. Do not paste keys into chat, prompts,
screenshots, logs or the report. Role separation here is at the configuration and
API scope level; both local processes run as your OS user, so this is not an OS
sandbox against arbitrary malicious Python code.

## 3. First run: reads, preview, then one order

Read-only credential and live replay checks:

```powershell
.\.venv\Scripts\python.exe trader.py --check
.\.venv\Scripts\python.exe guardian.py --check
.\.venv\Scripts\python.exe verify_market.py
```

`--check` needs only the Ledger key to be filled; provider placeholders may remain.
The replay check saves the public descriptor to `.state/market-descriptor.json`.
To verify the guide's three full BTC fixtures with the original default descriptor:

```powershell
.\.venv\Scripts\python.exe verify_market.py --descriptor .state\market-descriptor.json
```

Those formula fixtures include a future date and are isolated from live trading.
They can differ if the platform changed its descriptor. Unit tests cover the
published baseline fixtures and a hand-calculated noise case; the full default
quote fixtures and live API behavior require the actual platform descriptor.

Preview one trading cycle. This calls OpenAI when eligible evidence is available but submits no proposal:

```powershell
.\.venv\Scripts\python.exe trader.py --once
```

When ready, propose one order, preview its guardian review, then submit that review:

```powershell
.\.venv\Scripts\python.exe trader.py --once --submit
.\.venv\Scripts\python.exe guardian.py --once
.\.venv\Scripts\python.exe guardian.py --once --submit
```

HOLD is normal when a theory has no eligible signal. It is logged locally and never
sent as a zero-quantity order. Check Transactions, Guardian Log, Escalations and
the portfolio after the first order. Only EXECUTED with a recorded fill is a trade.
Preview still makes read requests, model calls and local logs; it can incur provider
charges. Re-running a preview does not guarantee the same later decision.

## 4. Short sessions

Run these in separate terminals with the same project interpreter and account:

```powershell
.\.venv\Scripts\python.exe guardian.py --loop --submit --duration 600
.\.venv\Scripts\python.exe trader.py --loop --submit --duration 600
```

The trader waits at least 60 seconds between cycles; the guardian at least 15,
plus jitter and any API cooldown. Session durations cannot exceed 600 seconds.
Network/model timeouts are bounded by the remaining session time; session expiry
leaves any unresolved order for recovery. Ctrl+C stops either program. The OS lock
prevents two copies of the same role using the same state directory.

## How decisions work

- `trader.py`: reconcile earlier work, fetch valid theory/policy/evidence, compute
  61 historical samples, ask OpenAI, validate its exact four fields, save intent,
  then propose at most one BUY/SELL. Invalid theory, replay or model output means HOLD.
- `guardian.py`: independently fetch fresh evidence, apply hard rules, load the
  order's exact theory snapshot, check strategy compliance, and assess simple
  anomalies. If permitted, ask OpenAI for the exact five-field review. Model or
  evidence failures ESCALATE when a valid review can be sent.
- `validation.py`: Decimal money, correct BUY-up/SELL-down cent rounding, exact
  and settled policy amounts, quantity precision, cash, holdings, quota equality,
  permissions, theory settings, model schema and reduced-only MODIFY checks.
- Before APPROVE/MODIFY, the guardian refreshes policy, counts, quote and portfolio
  and reruns hard rules, including per-buy budget. The server then applies its own
  execution checks. An HTTP success alone never proves that a trade executed.
- `market.py`: Appendix A replay, integer noise, no future samples, version refresh,
  and one descriptor refresh on mismatch before HOLD. Only numeric strategy rules
  are executable; prose cannot override them. Position fraction limits each BUY,
  not total exposure. Repeated signals may accumulate a position.
- `llm.py`: JSON schemas, trust-boundary prompts, bounded requests, no automatic
  provider retries, no Ledger credentials. Requests use `store=False`; incomplete,
  failed, refused or malformed responses fail safely. News and trader explanations are data.
- `client.py`: fixed canonical HTTPS origin, role endpoint allowlists, no redirects,
  1.1-second request spacing, read retries, shared cooldown and uncertain-write errors.
- `storage.py`: atomic journals, saved immutable theory snapshots, role locks and
  JSONL evidence. Treat local files as private evidence, not tamper-proof audit logs.

The guardian blocks hard violations. It escalates orders at/above the dashboard
escalation threshold, obvious instruction-injection warnings, and sizes over three
times the median of at least three recent completed trades. Risk scores for these
deterministic cases are fixed explanatory values, not calibrated probabilities;
otherwise the validated model supplies the risk score and decision. MODIFY is a
model-requested reduction that must pass every final check. To demonstrate
size-based escalation, set its threshold below the hard transaction maximum.

Text scanning is a basic warning mechanism. The model also sees news trust metadata,
reasoning, key labels and recent history, but Ledger exposes no IP/location/key-use
telemetry. This implementation cannot prove key theft or detect every injection.
It does not assess profitability. The platform remains the final execution backstop.

## Recovery

An uncertain proposal is never automatically resent, even after restarting. Inspect
Transactions and the dashboard, identify the order matching the saved intent, then:

```powershell
.\.venv\Scripts\python.exe trader.py --resolve-id 42
```

This validates the symbol, action, quantity and theory against available history,
then links the saved intent to that ID. If and only if you personally verified on
the dashboard that no order was created, you can record that verification:

```powershell
.\.venv\Scripts\python.exe trader.py --confirm-no-order
```

Neither command sends an order. Never clear state to bypass an unresolved trade.
For a lost review response, the guardian checks history; if finished it records the
outcome, and if still pending it gathers fresh evidence before reviewing again.
Ledger prevents duplicate execution of a finished transaction. If history no longer
contains the transaction, resolve ambiguity on the dashboard before proceeding.
429/503 pauses requests rather than forcing an escalation during cooldown.

## Tests and course evidence

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These tests use an in-memory API and model stubs: no keys, real network calls,
provider charges or live trades. They cover normal execution and balance changes,
preview, invalid model output, money rounding, injection warnings, quota equality,
policy changes during review, enlarged MODIFY, missing provenance and lost writes.
Local simulated fills do not count toward the course's live-trade requirement.

For the report, run at least three deliberate dashboard scenarios, one at a time:
oversized order, unsupported sale, untrusted news or controlled frequency burst.
Record setup, expected/actual decisions, transaction IDs, logs and whether your
guardian or the server blocked execution. Pause the trader while isolating attacks.
Respect the simulator's cooldown and do not flood the service to test HTTP limits.

Collect at least 20 completed BUY/SELL fills across the team, with every assigned
currency represented, in sessions of at most 10 minutes. Preserve per-session
times, theory versions, portfolio samples, outcomes and each member's contribution.
Report return and maximum drawdown, with cash and suitable buy-and-hold comparisons.
Do not force trades or weaken policy to reach the minimum. This implementation logs
agent decisions; portfolio performance analysis, report and slides remain team work.

## Sources and AI disclosure

The design follows the supplied COSC 435 Project Description and Student Development
Guide, especially sections 6-9 and Appendices A-D. The replay formula is adapted from
Appendix A; the model schemas and HTTP transport requirements follow the guide.
The provider adapter uses OpenAI's official SDK and structured-output documentation linked above.

AI assistance: Codex generated the initial implementation, tests and these run
instructions on 2026-11-07. The team should review, understand and validate the code,
record subsequent AI assistance, and disclose it in the final report as required.
No live credentials, authenticated API requests or paid model calls were used during
initial development. SDK request construction and agent behavior were tested locally.
Codex subsequently migrated the model adapter, private/example config fields,
dependency and tests to OpenAI at the student's request. Ledger keys were preserved.
