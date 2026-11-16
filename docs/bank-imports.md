# Bank uploads and reporting

Historical monthly rows and individual bank transactions are separate sources.
Uploading bank detail for a historical month can double count consumption. The
preview flags historical-month overlap; the dashboard's source filter should be
used until those sources have been reconciled. Historical aggregates are excluded
from partial-month date filters, with a warning.

## N26

Requires the 11 documented headers (order may vary), UTF-8 with optional BOM,
quoted fields and a consistent column count. Booking date drives the reporting
month; value date remains separate. `Amount (EUR)` retains its sign in
`source_entries.signed_booked`. Transactions store a positive magnitude and an
explicit kind. Negative Presentment entries suggest expenses; other transaction
types and positive amounts remain unresolved until reviewed. Positive values are
never automatically income. Original amount/currency, rate, partner IBAN,
payment reference, type and account remain available with the untouched raw row.
No recurring payment is confirmed automatically.

## Garanti card statements

File format is detected from bytes: ZIP-based XLSX uses openpyxl; OLE-based XLS
uses xlrd. A renamed XLSX with `.xls` extension is handled correctly. HTML/text
masquerading as Excel, encrypted files, PDF and unsupported exports are rejected;
they need a genuine XLS/XLSX export. No workbook macros or cell formulas execute.
Formula-based transaction dates or amounts must be exported as values first.

Each sheet is scanned for a TL/TRY or EUR card section, then its Date / Transaction /
Tag / Bonus / Amount(...) header. Blank rows and repeated headers are supported.
Card IDs stay separate from currency; different masked numbers are not merged.
Known total/subtotal labels are not purchases. Dated rows without a valid section
and header produce errors instead of being silently imported. Turkish decimal
strings and DD/MM/YYYY dates are parsed explicitly. Numeric spreadsheet cells
are converted once to their decimal text; exact source decimal formatting cannot
be recovered from an Excel numeric cell's binary representation.

Negative card entries suggest expenses. Positive Card Payment / Cep Şube Ödeme
entries suggest repayments. Explicit refund/iade entries suggest refunds; other
positive card entries remain unresolved. Negative settlement reversals remain
unresolved. Review all suggestions. Bank tags and bonus are metadata, not
additional purchases. There is no automatic mapping from a merchant to a
subscription. Suggested categories remain editable.

## Preview and persistence

Preview corrections can change booking date, signed booked amount, kind,
category, person and one-off status. Original raw values remain preserved.
Correct malformed source rows in the file and upload again. A file containing
parse errors cannot be saved partially. Any invalid review edit rejects the
whole confirmation before writes begin.

SHA-256 file fingerprints prevent exact reimports. Potential overlap across
exports, and repeated identical rows within an export, require keep/skip review.
Merchant/date/amount matches are never deleted automatically. Source/account/card
identity helps flag candidates but is not proof of duplication. Edited values,
different export descriptions or missing bank transaction IDs can limit duplicate
detection. Separate source files are not automatically reconciled.

The limit is 12 files, 15 MB each, 40 MB combined, 15,000 rows per file and 100 MB
expanded XLSX data. Temporary previews are process-local and expire after two
hours. Original files are not persisted; normalized fields, original row values,
filename, sheet, source row and import batch are persisted in ignored SQLite.

## Reporting and SQL

All financial reporting arithmetic runs in Python Decimal. Currencies remain
separate; saved exchange rates never silently convert totals. Charts convert
final numbers to floats only for display. Consumption excludes transfers,
repayments and unresolved entries and subtracts refunds. N26 signed account
movements are shown independently. Credit-card purchases and repayments are not
added together as consumption. Bank balances, household cash availability and
import completeness are not inferred.

The SQL workspace and local model operate on the selected saved/preview scope.
Explicit table/function allowlists and isolated query snapshots prohibit writes,
ATTACH, PRAGMA, file access, extensions and arbitrary functions. `DECIMAL_SUM`
provides exact aggregation and `DECIMAL_NEG` negates decimal strings. Ordinary
SQL casts/arithmetic can still create approximate floating-point results; use
the supplied decimal functions for financial totals. Queries have a 1.5-second
execution budget and a 1,000-row result limit. Data/schema lookup is available to
the model through `data_inventory`. Model prose is not an accounting authority;
inspect the returned tool evidence and executed SQL.

The UI's date/currency/source filters apply to the dashboard only. SQL and chat
can query the full selected scope; give their desired filters explicitly.
Suggestions identify unclassified rows and largest recorded groups; they do not
claim overspending or propose approved budgets without budget/income context.


Web chat uses an Ollama schema-constrained JSON SQL plan as its first data step.
The application executes that plan through `read_sql` before allowing financial
prose; a model cannot satisfy the guard merely by claiming it ran SQL. Failed SQL
is fed back within the bounded loop. An invalid plan or exhausted loop returns
an error without presenting an unverified draft. This does not prove every
statement in the later explanation; the SQL result remains authoritative.
