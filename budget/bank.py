"""Import persistence, review validation and exact reporting for bank sources."""
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from .store import Store, money, month_bounds
from .importers import CATEGORY_IDS, KINDS

BANK_SCHEMA = '''
CREATE TABLE IF NOT EXISTS import_batches (
 id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
 source_type TEXT NOT NULL, file_format TEXT NOT NULL, imported_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS source_entries (
 transaction_id INTEGER PRIMARY KEY REFERENCES transactions(id),
 batch_id INTEGER NOT NULL REFERENCES import_batches(id), row_key TEXT UNIQUE NOT NULL,
 filename TEXT NOT NULL, sheet TEXT NOT NULL, source_row INTEGER NOT NULL,
 source_type TEXT NOT NULL, value_date TEXT, signed_booked TEXT NOT NULL,
 account TEXT NOT NULL, card_id TEXT, section TEXT NOT NULL, bank_tag TEXT,
 bonus TEXT, original_amount TEXT, original_currency TEXT, exchange_rate TEXT,
 payment_reference TEXT, transaction_type TEXT, partner_iban TEXT, raw_json TEXT NOT NULL);
'''


def initialize(store):
    store.db.executescript(BANK_SCHEMA)
    with store.db:
        store.db.executemany('INSERT OR IGNORE INTO categories(id,parent) VALUES (?,NULL)',[(c,) for c in CATEGORY_IDS])
        if not store.db.execute('SELECT 1 FROM groups WHERE name=?',('shopping_group',)).fetchone():
            store.db.executemany('INSERT INTO groups VALUES (?,?)',[('shopping_group',c) for c in ['shopping','clothing','electronics']])


def signature(entry):
    return (entry['booking_date'],entry['currency'],money(entry['signed_booked']),
            entry['merchant'],entry['account'],entry.get('card_id'),entry['source_type'])


def duplicates(store,batches):
    existing=defaultdict(list)
    for row in store.db.execute('''SELECT t.id,t.booking_date,t.currency,t.merchant,s.signed_booked,s.account,s.card_id,s.source_type
      FROM transactions t JOIN source_entries s ON t.id=s.transaction_id'''):
        existing[signature(dict(row))].append(f"saved:{row['id']}")
    for row in store.db.execute("SELECT id,month FROM transactions WHERE booking_date IS NULL"):
        # Monthly historical sources can overlap bank detail without matching merchant/date.
        existing[('historical_month',row['month'])].append(f"historical:{row['id']}")
    seen=defaultdict(list)
    hashes=set()
    for batch in batches:
        batch['already_imported']=bool(store.db.execute('SELECT 1 FROM import_batches WHERE digest=?',(batch['digest'],)).fetchone()) or batch['digest'] in hashes
        hashes.add(batch['digest'])
        for e in batch['entries']:
            sig=signature(e)
            refs=existing[sig]+seen[sig]
            historical=existing[('historical_month',e['month'])]
            e['duplicate_candidates']=refs
            e['historical_overlap']=historical
            if refs:
                e['warnings'].append('Possible overlap; explicitly keep or skip this row. Repeated purchases may be legitimate.')
            if historical:
                e['warnings'].append('Historical monthly rows overlap this month. Keep sources separate until reconciled.')
            seen[sig].append(e['key'])


def reviewed_entries(store,batches,edits,require_duplicate_decisions=True):
    if not isinstance(edits,dict):
        raise ValueError('Edits must be an object keyed by preview row key.')
    valid_categories={r[0] for r in store.db.execute('SELECT id FROM categories')}
    known_keys={e['key'] for b in batches for e in b['entries']}
    if set(edits)-known_keys:
        raise ValueError('Unknown preview row key.')
    result=[]
    for b in batches:
        if b.get('already_imported'):
            continue
        if b['errors']:
            raise ValueError(f"{b['filename']}: fix parsing errors and upload again before saving.")
        for original in b['entries']:
            edit=edits.get(original['key'],{})
            if not isinstance(edit,dict) or set(edit)-{'decision','kind','category','person','booking_date','signed_booked','one_off'}:
                raise ValueError('Unsupported row correction.')
            decision=edit.get('decision')
            if decision not in (None,'keep','skip'):
                raise ValueError('Invalid duplicate decision.')
            if require_duplicate_decisions and original.get('duplicate_candidates') and decision not in {'keep','skip'}:
                raise ValueError('Explicitly keep or skip every possible duplicate before saving.')
            if decision=='skip':
                continue
            row={**original,**{k:v for k,v in edit.items() if k!='decision'}}
            if row['kind'] not in KINDS or row['category'] not in valid_categories:
                raise ValueError('Invalid kind or category.')
            if row['person'] is not None and (not isinstance(row['person'],str) or len(row['person'])>100):
                raise ValueError('Person must be text, up to 100 characters.')
            if type(row.get('one_off',False)) is not bool:
                raise ValueError('One-off must be true or false.')
            row['booking_date']=date.fromisoformat(row['booking_date']).isoformat()
            row['month']=row['booking_date'][:7]
            row['signed_booked']=str(money(row['signed_booked']))
            row['amount']=str(abs(money(row['signed_booked'])))
            result.append((b,row))
    return result


def insert_row(db,batch_id,e):
    cursor=db.execute('''INSERT INTO transactions
        (booking_date,month,amount,currency,kind,category,person,household,merchant,tags,one_off,recurring_id,source)
        VALUES (?,?,?,?,?,?,?,'home',?,?,?,NULL,?)''',
        (e['booking_date'],e['month'],e['amount'],e['currency'],e['kind'],e['category'],e['person'],e['merchant'],
         ('historical_import' if e['source_type']=='historical' else 'bank_import|classification_review'),int(e.get('one_off',False)),
         json.dumps({'filename':e['filename'],'sheet':e['sheet'],'row':e['row'],'type':e['source_type']},ensure_ascii=False)))
    columns=['filename','sheet','source_type','value_date','signed_booked','account','card_id','section','bank_tag',
             'bonus','original_amount','original_currency','exchange_rate','payment_reference','transaction_type','partner_iban']
    db.execute(f'''INSERT INTO source_entries
      (transaction_id,batch_id,row_key,source_row,{','.join(columns)},raw_json)
      VALUES ({','.join('?' for _ in range(21))})''',
      (cursor.lastrowid,batch_id,e['key'],e['row'],*[e.get(k) for k in columns],json.dumps(e['raw'],ensure_ascii=False)))


def commit(store,batches,edits):
    rows=reviewed_entries(store,batches,edits)
    inserted=0
    with store.db:
        for batch in batches:
            if batch.get('already_imported') or store.db.execute('SELECT 1 FROM import_batches WHERE digest=?',(batch['digest'],)).fetchone():
                continue
            batch_id=store.db.execute('INSERT INTO import_batches(digest,filename,source_type,file_format) VALUES (?,?,?,?)',
                (batch['digest'],batch['filename'],batch['source_type'],batch['format'])).lastrowid
            for b,row in rows:
                if b is batch:
                    insert_row(store.db,batch_id,row)
                    inserted+=1
    return inserted


def preview_store(saved,batches,edits=None):
    store=Store()
    initialize(store)
    # Preserve the user's editable categories and groups in preview analysis.
    saved.db.backup(store.db)
    with store.db:
        store.db.execute('DELETE FROM source_entries')
        store.db.execute('DELETE FROM transactions')
        store.db.execute('DELETE FROM import_batches')
        store.db.execute('DELETE FROM coverage')
        store.db.execute('DELETE FROM recurring')
        store.db.execute('DELETE FROM plans')
        store.db.execute('DELETE FROM budgets')
    usable=[b for b in batches if not b.get('already_imported') and not b['errors']]
    # Preview can show unconfirmed duplicate candidates; persistence still requires a decision.
    rows=reviewed_entries(saved,usable,edits or {},False)
    with store.db:
        for b in usable:
            batch_id=store.db.execute('INSERT INTO import_batches(digest,filename,source_type,file_format) VALUES (?,?,?,?)',
                (b['digest'],b['filename'],b['source_type'],b['format'])).lastrowid
            for batch,e in rows:
                if batch is b:
                    insert_row(store.db,batch_id,e)
    return store


def dashboard(store,currency_code='EUR',start=None,end=None,source='all',group_by='category',search='',category='all'):
    if group_by not in {'category','section','account','source_type'}:
        raise ValueError('Unsupported grouping.')
    rows=[dict(r) for r in store.db.execute('''SELECT t.*,s.value_date,s.signed_booked,s.account,s.card_id,s.section,
        s.bank_tag,s.bonus,s.original_amount,s.original_currency,s.exchange_rate,s.payment_reference,s.transaction_type,
        s.partner_iban,s.filename,s.sheet,s.source_row,COALESCE(s.source_type,'historical') source_type
        FROM transactions t LEFT JOIN source_entries s ON s.transaction_id=t.id ORDER BY t.month DESC,t.booking_date DESC,t.id DESC''')]
    currencies=sorted({r['currency'] for r in rows})
    sources=sorted({r['source_type'] for r in rows})
    all_months=sorted({r['month'] for r in rows})
    for v in [start,end]:
        if v:date.fromisoformat(v)
    if start and end and start>end:raise ValueError('Start is after end.')
    selected=[]
    partial=set()
    for r in rows:
        if r['currency']!=currency_code or source!='all' and r['source_type']!=source:
            continue
        if category != 'all' and r['category'] != category:
            continue
        if search and search.casefold() not in r['merchant'].casefold():
            continue
        if r['booking_date']:
            if start and r['booking_date']<start or end and r['booking_date']>end:
                continue
        else:
            first,last=month_bounds(r['month'])
            if start and last.isoformat()<start or end and first.isoformat()>end:
                continue
            if start and first.isoformat()<start or end and last.isoformat()>end:
                partial.add(r['month'])
                continue
        selected.append(r)
    zero=Decimal(0)
    monthly=defaultdict(lambda:defaultdict(lambda:zero))
    groups=defaultdict(lambda:zero)
    category_totals=defaultdict(lambda:zero)
    totals=defaultdict(lambda:zero)
    for r in selected:
        amount=money(r['amount'])
        kind=r['kind']
        totals[kind]+=amount
        monthly[r['month']][kind]+=amount
        if kind in {'expense','refund'}:
            net=amount if kind=='expense' else -amount
            totals['consumption']+=net
            monthly[r['month']]['consumption']+=net
            category_totals[r['category'] or 'uncategorized']+=net
            groups[r[group_by] or ('historical' if group_by in {'section','account'} else 'uncategorized')]+=net
        if r['source_type']=='n26':
            flow=money(r['signed_booked'])
            totals['n26_net_account_movement']+=flow
            monthly[r['month']]['n26_net_account_movement']+=flow
    earliest=min((r['booking_date'] or r['month']+'-01' for r in selected),default=None)
    latest=max((r['booking_date'] or month_bounds(r['month'])[1].isoformat() for r in selected),default=None)
    limitations=['Import completeness has not been inferred from these files. Missing records are not zero spending.',
                 'N26 signed movements describe account activity. Card purchases and card repayments must not be added together as consumption.']
    if any(r['source_type']=='historical' for r in selected) and any(r['source_type']!='historical' for r in selected):
        limitations.append('Historical monthly totals and bank details may overlap. Filter by source until reconciled; the combined total may double count spending.')
    if partial:limitations.append('Monthly-only historical entries excluded from partial months: '+', '.join(sorted(partial)))
    unresolved=[r for r in selected if r['kind']=='unresolved']
    uncategorized=[r for r in selected if r['category'] in (None,'uncategorized')]
    suggestions=[]
    if unresolved:suggestions.append({'type':'review','text':f"Review {len(unresolved)} unresolved entries before treating totals as complete."})
    if uncategorized:suggestions.append({'type':'categorize','text':f"Categorize {len(uncategorized)} entries to make category charts more useful."})
    if groups:
        largest=max(groups,key=groups.get)
        suggestions.append({'type':'trend','text':f'Largest recorded {group_by}: {largest}.','amount':str(groups[largest])})
    def series(d):return {k:str(v) for k,v in d.items()}
    return {'currency':currency_code,'currencies':currencies,'sources':sources,'all_months':all_months,'categories':sorted({r['category'] for r in rows if r['category']}),
            'start':start or earliest,'end':end or latest,'group_by':group_by,'source':source,
            'record_count':len(selected),'totals':series(totals),'monthly':[{'month':m,**series(v)} for m,v in sorted(monthly.items())],
            'groups':[{'name':k,'amount':str(v)} for k,v in sorted(groups.items(),key=lambda kv:kv[1],reverse=True)],
            'category_totals':[{'name':k,'amount':str(v)} for k,v in sorted(category_totals.items())],
            'transactions':selected[:500],'rows_truncated':len(selected)>500,
            'unresolved_count':len(unresolved),'uncategorized_count':len(uncategorized),
            'limitations':limitations,'suggestions':suggestions,
            'coverage':[dict(r) for r in store.db.execute('SELECT * FROM coverage WHERE currency=?',(currency_code,))]}
