# Data analyzer

Open [data_analyzer.ipynb](data_analyzer.ipynb) in your IDE and select the Python
interpreter at `../.venv/bin/python` as the notebook kernel. Run all cells from
top to bottom. The notebook finds the project root from either the repository
root or this directory.

Notebook dependencies are already installed in this workspace. To recreate them:

```bash
.venv/bin/python -m pip install -r notebooks/requirements.txt
```

Change `DATABASE_NAME` in the first code cell between `demo.sqlite` and
`budget.sqlite`. The notebook opens an existing database in read-only mode;
it never creates a new database. Change the drill-down cell's month, category,
person, currency or merchant search to inspect matching records.

Includes table counts and schemas, records, exact-decimal monthly and category
calculations, charts, original-source reconciliation, review flags, repeated-row
candidates, and import coverage. Chart values alone use floats. Empty databases
are supported. Original demo labels differ from their simulated reporting months.

All 10 code cells were executed with both the populated demo database and the
empty real database. File hashes confirmed neither database changed. Notebook
schema validation also passed. The cells were checked in a headless Python
process; the IDE's interactive kernel/display was not tested.

Outputs are deliberately cleared in the saved notebook. Clear them again before
sharing or committing it so household records do not enter Git. Local SQLite
files and `.local/` source copies are ignored by Git.
