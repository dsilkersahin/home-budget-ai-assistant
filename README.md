# Home Budget AI Assistant

A local budgeting app to import statements, track monthly spending, explore
categories, and ask questions about your records. Data stays on your computer,
with a SQLite database and an optional local AI assistant powered by Ollama.

## Start the app

Requires Python 3.10 or newer. From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-web.txt
python -m budget --db budget.sqlite web
```

Open **http://127.0.0.1:8000**.

## How to use

1. Upload supported CSV or Excel statements and click **Analyze files**.
2. Review transactions and categories, then confirm and save.
3. Filter the dashboard to explore monthly totals and spending categories.
4. Use the read-only SQL workspace or ask the assistant about your records.

For AI chat, run Ollama locally with the `qwen3.5:9b` model available.
Include the period and currency in your questions. The dashboard and SQL
workspace work without the model.

Files must match a supported statement layout. See [import details](docs/bank-imports.md).
Database files and transaction exports are excluded from Git.

## Screenshots

![Monthly spending dashboard](docs/ui/dashboard.png)

![Statement import](docs/ui/statement-import.png)

![Local budget assistant](docs/ui/budget-assistant.png)
