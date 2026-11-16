"""Optional live Qwen SQL check using synthetic in-memory imports only."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from budget.store import Store
from budget.bank import initialize,duplicates,commit
from budget.importers import parse_file
from budget.analysis import Analysis
from budget.sql_tools import WebTools
from budget.chat import SQLChat
s=Store();initialize(s)
files=[parse_file('october.csv',(ROOT/'examples/n26-october.csv').read_bytes()),parse_file('november.csv',(ROOT/'examples/n26-november.csv').read_bytes())]
duplicates(s,files);commit(s,files,{})
chat=SQLChat(WebTools(Analysis(s)),'qwen3.5:9b')
result=chat.ask("Use read_sql to execute exactly this read-only query: SELECT DECIMAL_SUM(amount) AS consumption FROM transactions WHERE kind='expense' AND currency='EUR'; Report the result as recorded consumption, not complete household spending. Show the SQL.")
assert any(e.get('rows')==[['57.25']] for e in result['evidence']),result
print(json.dumps(result,ensure_ascii=False,indent=2))
s.db.close()
