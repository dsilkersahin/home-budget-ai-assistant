# Implementation scope

This first increment implements the requested analysis and forecasting backend:
SQLite records, editable category groups, exact-decimal calculations, period
resolution, comparison, drill-down, recurring candidates, conservative forecasts,
scenarios, backtesting, and a bounded Ollama tool loop. Historical analysis is
available immediately through the CLI/tools. Forecasts require explicit import
coverage. The user-selected local model and limited validation are recorded below.

A subsequent increment adds a local FastAPI web app with N26 CSV and
Garanti XLS/XLSX import previews, explicit confirmation, source provenance,
monthly/category/section dashboards, a SQL explorer, and local chat SQL tools.
The broader roadmap still includes historical workbook mapping, saved-row
editing, reviewed budget proposals, and backup/export workflows.

Architecture: `store.py` owns SQLite and validated writes; `analysis.py` owns
read-only calculations; `tools.py` validates model arguments; `chat.py` owns
bounded, local-only model calls. Money is stored as decimal strings. Dates are
ISO calendar dates; monthly aggregates retain a month without a fabricated day.
Currencies and consumption/card cash flow remain separate. Forecasts/scenarios
have no persistence tool and cannot approve budgets.

## Local model setup

User-selected model: `qwen3.5:9b` (Ollama manifest ID `56671c2ab938`,
6.6 GB download), installed with Ollama 0.40.16 in `.local/`. The
[official model card](https://huggingface.co/Qwen/Qwen3.5-9B) lists Apache 2.0.
On this WSL machine, Ollama detects an NVIDIA RTX 4070 Laptop GPU (8 GB VRAM)
and reports 88% GPU / 12% CPU placement at 8192 context tokens. The runtime is
started explicitly via `scripts/serve-model.sh`; no system service was installed.
The temporary download decompressor (`zstandard==0.25.0`) was installed only in
`.venv`; it is not an application runtime dependency.

Live smoke test (2026-11-12): English and Turkish each selected the spending
summary tool, retrieved 42.35 EUR over 2026-08-01 through 2026-10-31 from a
synthetic in-memory store, and mentioned incomplete imports. Both passed tool
evidence assertions. This does not validate broader tool planning, follow-ups,
forecast quality, or every statement in model explanations. In particular,
unknown completeness is not proof that records are missing.


## Bank upload implementation

`importers.py` parses bytes without persistence. `bank.py` validates review edits,
flags possible overlaps, saves confirmed batches in one transaction, and reports
exact-decimal totals. `source_entries` extends existing transaction rows without
rewriting monthly historical data. `sql_tools.py` exposes a read-only snapshot;
`web.py` owns temporary upload previews, scoped chat sessions and local endpoints.
Static HTML/CSS/JS is packaged under `budget/static`. No Node build is needed.

The authorizer is attached only to an isolated query connection (Python 3.10
cannot reliably disable it via `set_authorizer(None)`). This also isolates SQL
from the connection used to save reviewed imports. SQLite money aggregation uses
a Decimal aggregate. Import coverage remains an explicit assertion, never a
byproduct of having uploaded a file.

Final web verification: 31 backend tests and the isolated Chromium browser flow
pass. A real Qwen3.5-9B structured SQL plan returned the verified 57.25 EUR sum
from the two synthetic N26 files. An initial native-tool attempt fabricated an
execution claim; this led to SQLChat's schema-constrained planning step and a
regression test. A successful data tool must run before web chat returns an
explanation. Financial prose can still misstate tool results, so evidence remains
authoritative. GPU offload is now capped at 24 layers to leave VRAM headroom.
