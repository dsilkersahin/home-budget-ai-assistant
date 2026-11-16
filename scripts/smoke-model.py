"""Optional real-model smoke test. Synthetic records live only in memory.
Run from the repository root: .venv/bin/python scripts/smoke-model.py
"""
import json
import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from budget.store import Store
from budget.analysis import Analysis
from budget.tools import Tools
from budget.chat import Chat

for language, question in [
    ('en', 'Use spending_summary: how much did our household spend in EUR on groceries in the last three completed months? Show the period and import limitations.'),
    ('tr', 'spending_summary aracını kullan: Son üç tamamlanmış ayda ev halkı olarak market (groceries) için EUR cinsinden ne kadar harcadık? Tarih aralığını ve veri eksiklerini belirt.'),
]:
    store = Store()
    store.category('groceries')
    store.add(amount='42.35',currency_code='EUR',kind='expense',category='groceries',booking_date='2026-10-09')
    chat = Chat(Tools(Analysis(store,today=date(2026,11,12))),'qwen3.5:9b',language)
    result = chat.ask(question)
    evidence = [r for r in result['evidence'] if r.get('consumption') == '42.35']
    assert evidence, f'{language}: no verified spending tool result'
    assert evidence[-1]['start'] == '2026-08-01'
    assert evidence[-1]['end'] == '2026-10-31'
    assert evidence[-1]['limitations']
    print(json.dumps({'language':language,'answer':result['answer'],'verified_total':evidence[-1]['consumption']},ensure_ascii=False),flush=True)
    store.db.close()
