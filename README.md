# Home Budget AI Assistant

A local Python/SQLite household budgeting application with a browser upload
dashboard, deterministic financial analysis, experimental guarded forecasts and
bounded Ollama chat. Import multiple supported CSV or Excel card statements,
review them, then explicitly save. Monthly historical ledger entries remain a
separate source type. Data and model processing stay on your computer.

## Interface overview

The dashboard brings statement imports, monthly spending, category breakdowns,
and a local budget assistant into one workspace. English and Turkish are available
from the language toggle.

![Dashboard with summary cards, monthly trends, spending breakdown, and budget assistant](docs/ui/dashboard.png)

**Statement import**

![Statement upload area for CSV and Excel files](docs/ui/statement-import.png)

**Local budget assistant**

![Budget assistant with suggested questions and a chat input](docs/ui/budget-assistant.png)

- **Start with your statements:** drag in multiple supported CSV or Excel statement
  files, then select **Analyze files** to review them before saving.
  Each batch supports up to 12 files, with a 15 MB limit per file.
- **Explore your records:** switch between **Saved database** and **Upload preview**,
  then filter the dashboard by year, month, category, currency, source, or date range.
- **See the totals:** summary cards show recorded consumption, signed account
  movement, card repayments, and the number of entries needing classification.
  Consumption is expenses less refunds, with card repayments excluded.
- **Follow the trends:** **Month by month** compares recorded income and expenses
  and includes a detailed monthly table. **Where it goes** breaks down spending
  using the selected grouping.
- **Ask your budget assistant:** use **Monthly summary**, **Top categories**, or
  **Review unknown entries**, or enter your own question. Calculations come from
  local tools, and supporting evidence is available to inspect. Chat cannot save
  imports or approve budgets; uploaded previews and saved records are queried
  separately.

Displayed totals describe the available records. Missing months or statements do
not establish zero spending or complete household coverage.

## Open the web app

Dependencies are installed in this workspace. From the project root:

```bash
source .venv/bin/activate
python -m budget --db budget.sqlite web
```

Open **http://127.0.0.1:8000**. Override `--port 8001` if the port is occupied.
On a fresh installation, install `requirements-web.txt` into a virtual environment
first. The web UI is buildless HTML/CSS/JavaScript served by FastAPI; Node is not
required. The CLI still works without web dependencies.

1. Choose or drop one or more supported CSV or Excel statement files.
2. Analyze files to create a temporary upload preview. No transactions are saved.
3. Review date, signed booked amount, kind, category, person, and one-off flags.
   Resolve possible overlaps by explicitly keeping or skipping each candidate.
   Apply corrections with **Update analysis preview**.
4. Inspect the **Upload preview** dashboard or query it with SQL/chat.
5. Click **Confirm & save reviewed rows** to persist reviewed records atomically.
   Identical file bytes are idempotent even when filenames differ. Parsing errors
   block the batch; fix the source and upload again. Repeated purchases are retained
   unless you explicitly skip them.

Currency, source, inclusive dates, merchant search, and grouping controls filter the
report. Category, statement section, account/card and source charts use exact backend
calculations. Monthly tables separate consumption, signed account movements,
card repayments, classified income and unresolved amounts. Transaction rows expose
original-currency metadata, bank tags, bonus, source sheet/row and value date.

The selected **Saved database** or **Upload preview** scope also applies to SQL
and chat. Chat uses the configured local Qwen3.5-9B model and shows tool evidence. Web chat first produces a schema-constrained SQL
plan, validates and executes it, then asks the model for an explanation;
manual SQL works even when Ollama is unavailable. A scoped conversation persists
across prompts and resets when imports or review edits change its data snapshot.
Dashboard display filters do not silently constrain SQL/chat: state the desired
period, currency and filters in the prompt or query.

Only bounded read-only SQL is accepted. `transactions` contains amounts as positive
decimal text and `kind` indicates financial meaning. Join `source_entries` on
`transaction_id` for signed booked amounts, card identities and import metadata.
Use `DECIMAL_SUM(amount)` for exact sums and `DECIMAL_NEG(amount)` for refund
subtraction; floating-point `SUM`, `AVG` and `TOTAL` are disabled. SQL is run on an
isolated snapshot with an authorizer, a 1.5-second execution limit and 1,000-row
output cap. LLM tools cannot confirm imports or execute database writes.

Two synthetic files in `examples/` can be uploaded together for testing. Their
combined expense total is **57.25 EUR** (October 42.35; November 14.90). Do not
confirm demo files into your real database; use `--db demo-upload.sqlite` for a
separate sandbox. The existing monthly-ledger `demo.sqlite` remains separate.

For chat, start `./scripts/serve-model.sh` only if Ollama is not already running.
An "address already in use" error typically means that server is already active.
The web app binds only to localhost. No hosting, synchronization or cloud fallback
is configured. The page has a persistent EN/TR toggle; some technical validation
and tool-evidence messages remain English.

## Run

Python 3.10 or newer; no runtime packages required. From this directory:

```bash
python3 -m budget --db budget.sqlite init
python3 -m budget --db budget.sqlite tool catalog '{}'
python3 -m budget --db budget.sqlite tool spending_summary '{"currency_code":"EUR","period":"last_three_months"}'
python3 -m unittest discover -s tests -v
```

Use `python` instead of `python3` if appropriate on Windows. The same commands
work in WSL/macOS with Python installed. Only Linux/Python 3.10 has been tested.
No data is seeded into the real database. CLI tool responses are JSON and remain
available without a model. The database is local to this machine; it does not sync.

Qwen3.5-9B is the configured default (`qwen3.5:9b`). The official Ollama
runtime and model weights are installed locally under ignored `.local/`.
Start the runtime in one terminal, then chat in another:

```bash
./scripts/serve-model.sh
```

```bash
source .venv/bin/activate
python -m budget chat --language tr
# Override the model if desired:
python -m budget chat --model qwen3.5:9b --language en
```

The server binds to `127.0.0.1:11434` with cloud features disabled and one
parallel request. Chat uses an 8K context, up to 2048 output tokens, and disables
thinking for tool responsiveness. GPU offload is capped at 24 layers to leave
VRAM headroom on this 8 GB laptop GPU. Requests allow up to five minutes for loading
or CPU offload. The client disables HTTP proxies and rejects redirects. There
is no cloud fallback. The Linux runtime launcher is intended for this WSL setup;
Windows/macOS native installations should run their own Ollama server with the
same downloaded model. No automatic model downloads happen during chat.
The model's explanation can still be wrong: returned `evidence` contains the
backend's authoritative calculations, filters and records.

## Data setup and analysis

For monthly historical entries, use the explicit Python API with verified records.
Bank statements should use the reviewed web import flow.
The following is a **synthetic in-memory example**, never a real import:

```python
from datetime import date
from budget.store import Store
from budget.analysis import Analysis
from budget.tools import Tools

store = Store()  # in-memory; use a filename for persistence
store.category('shopping')
store.category('clothing', parent='shopping')
store.category('electronics', parent='shopping')
store.category('travel')
store.group('shopping_group', ['shopping', 'clothing', 'electronics'])
store.add(amount='42.35', currency_code='EUR', kind='expense',
          category='clothing', booking_date='2026-10-09', person='Menekşe')
tools = Tools(Analysis(store, today=date(2026, 11, 12)))
result = tools.call('spending_summary', {
    'currency_code': 'EUR', 'categories': ['shopping_group']})
assert result['start'] == '2026-08-01'
assert result['end'] == '2026-10-31'
assert result['consumption'] == '42.35'
```

Categories and groups use editable stable IDs. Define shopping consistently via
the group; the model asks when the meaning is unresolved. A group expands to a
set of descendants, so selecting both a parent and its children counts each
record once. Different records are never deduplicated by merchant/date/amount.
Person and household filters are exact; `catalog` lists available names.
Unassigned persons are omitted by a person filter. No exchange-rate conversion
is inferred. EUR and TRY are queried independently.

Transaction amounts are nonnegative decimal **strings**; kinds determine their
meaning. Refunds reduce consumption; transfers, card repayments and unresolved
entries are excluded. Net cash flow is withheld until account-level cash movements and card settlement
timing are modeled; adding purchases and repayments would count card spending
twice. Monthly-only records have `month` and no invented booking
date. They are excluded with a warning from partial-month queries.

`last_three_months` means the last three completed calendar months.
`rolling_three_months` means the interval after the same calendar day three
months earlier through today (clamped to the target month's last day).
`current_plus_two` means the first of two months earlier through today.
`last_month`, `current_month`, or explicit inclusive `start` and `end` are also
supported. Monthly averages divide by calendar months touched, so use full
calendar months for a comparable monthly average. All responses show exact dates.

Tools:

- `spending_summary`: totals, monthly category breakdowns, average, coverage, supporting transactions.
- `period_comparison`: preceding equally long calendar period, deltas, supporting records; contributors do not establish causes.
- `transaction_drill_down`: same filters and exact records behind the summary.
- `recurring_detection`: repeated merchant/amount candidates across months; never auto-confirms subscriptions.
- `month_end_forecast`, `next_month_forecast`: experimental, read-only consumption projections.
- `scenario_simulation`: explicit upcoming expenses and a savings target; never writes budgets.
- `baseline_backtest`: time-ordered monthly mean, median and last-month baseline errors.
- `catalog`: category/group IDs, currencies, persons and import coverage.

Historical tools in a `Tools` session inherit the last successful period and
filters. Supply `person`, `exclude_categories`, or `exclude_tags` to narrow a
follow-up. An explicit new period replaces the prior dates. `period_comparison`
compares the active period with its predecessor. Start a new `Tools`/chat session
to reset all filters. Forecast tools deliberately accept their own explicit
household/person filters; they do not inherit historical category exclusions.

## Forecast safeguards

Forecasts remain experimental. Uploading a file does not assert continuous import completeness.
`Store.set_coverage(start, through, currency_code, household)` asserts a
**continuous, complete household history across all relevant accounts**, not just
that an import has run. Do not assert completeness on incomplete data. The
current-month estimate requires coverage through today; next-month requires all
three completed historical months. Coverage never comes from the LLM.

Use `Store.confirm_recurring(...)` only after reviewing a candidate. It represents
a confirmed monthly consumption payment (not a card repayment); `day` is the
scheduled day, clamped by month length conceptually, and unpaid past-due amounts
remain expected. Confirmed records need matching `recurring_id` links. Plausible
unlinked matches cause withholding to avoid double counting. Historical monthly
aggregates must likewise identify confirmed recurring components separately.
Mixed aggregate-plus-detail sources require reconciliation before entry.

Next-month routine category spending uses the prior three monthly averages,
excluding flagged one-offs, travel category/tag and linked recurring payments.
Confirmed active recurring amounts are added once. Current month uses recorded
routine daily pace times remaining days, actuals, and unrecorded confirmed
payments. Travel and other unusual purchases remain in current actuals. Add
future travel/one-offs with `scenario_simulation`. Explicitly mark one-offs;
unflagged unusual expenses will affect the routine baseline.

`Store.set_income` supplies expected monthly income. A person-filtered forecast
withholds household income/surplus, since household income cannot be attributed
to a person. `Store.set_budget` stores an explicitly approved category target;
model tools cannot call it. Over-budget categories compare estimated consumption
to these targets. Surplus is income minus consumption, **not bank cash remaining**.
Scenarios return additional savings needed but never approve category changes.

There are no calibrated prediction intervals. Backtesting requires three complete
months before each outcome and reports MAE for simple consumption baselines;
it does not claim to validate the recurring-adjusted model. Historical recurring
configuration is not versioned, so that model is deliberately excluded from
backtests to avoid future information leakage.

## Verification and remaining work

Tests use synthetic in-memory fixtures and mocked bilingual model tool calls.
They cover precision, refunds/cash-flow separation, periods/year/leap boundaries,
category overlap, comparisons, person follow-ups, monthly-only records, coverage,
recurring ambiguity, scenario reconciliation, read-only tools, and bounded chat.
A real `qwen3.5:9b` smoke test also passed in English and Turkish on this WSL
machine: both requests called the spending tool and retrieved the correct
synthetic total (42.35 EUR) and period (2026-08-01 through 2026-10-31). Run
`.venv/bin/python scripts/smoke-model.py` with the server running to repeat it.
This is a narrow integration check, not a comprehensive language/agent evaluation;
model prose may still misstate what incomplete coverage proves. Check tool evidence.
The upload implementation adds tests for CSV BOM/quotes/empty values,
positive unclassified entries, signed account movements, sectioned Excel statements
and genuine XLS, repeated headers, Turkish numbers, provenance, corrections,
idempotence, overlap review, atomic preview/confirmation and SQL authorization.
A Chromium browser smoke test covers multi-file upload, preview corrections,
SQL totals/write rejection, confirmed persistence, mocked chat/evidence UI,
section charts, EN/TR and mobile overflow. It uses an isolated temporary database.
Windows/macOS native execution and real bank files remain unverified. Historical Excel ledgers can be imported using the `import-history` command below;
the web upload flow accepts bank statements.
See [implementation scope](docs/implementation.md).

## Inspect the data in a notebook

Open [notebooks/data_analyzer.ipynb](notebooks/data_analyzer.ipynb) and select
`.venv/bin/python` as the kernel. It defaults to the demo database and provides
read-only schema inspection, record browsing, monthly/category totals, charts,
source reconciliation and data quality checks. See
[notebook instructions](notebooks/README.md) for filters and dependencies.

## Web import verification

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
# Optional browser QA (first download Chromium):
PLAYWRIGHT_BROWSERS_PATH="$PWD/.local/browsers" .venv/bin/python -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH="$PWD/.local/browsers" .venv/bin/python tests/browser_smoke.py
```

See [bank import details](docs/bank-imports.md) for classification, coverage,
overlap and supported-file limitations. Uploaded previews expire after two hours
or a server restart. Review up to 100 rows per file page; reports calculate over
all valid staged rows. Dashboards show at most 500 transactions at once; narrow
filters for drill-down. Refresh a page after a server restart to obtain its new
local request token.

An optional live SQL/model integration check is available as
`.venv/bin/python scripts/smoke-sql-chat.py`. It uses the synthetic example CSVs
in memory, asserts a 57.25 EUR SQL result, and never writes to the real database.

## Import monthly workbook history

Import an existing monthly Excel ledger into your local database:

```bash
.venv/bin/python -m budget --db budget.sqlite import-history /path/to/monthly-ledger.xlsx
```

Choose **Saved database** and **Source: historical** in the dashboard to inspect
imported monthly records. Use the year filter to select the relevant period.

The importer expects the supported monthly ledger layout; arbitrary spreadsheets
may need adaptation. Identical workbook imports are skipped. Each literal amount
in column B becomes one monthly record with workbook, sheet and row provenance;
no daily booking date is invented. Formula totals and side calculations are
excluded to avoid counting amounts twice. Negative expenses are refunds.
Category assignments use label and section rules; unmatched entries remain
uncategorized. Worksheet names supply the month. Missing months are absent
records, and an imported month does not establish complete coverage.

Existing statement records remain present; filter by source when periods overlap.
Personal workbooks and local databases are excluded from Git.
