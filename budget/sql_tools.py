"""Bounded, authorizer-enforced read-only SQL for saved or staged records."""
import sqlite3
import time
from .store import money
from .tools import Tools, schema, validate

ALLOWED_TABLES={'transactions','source_entries','categories','groups','coverage','recurring','plans','budgets'}
ALLOWED_FUNCTIONS={'count','min','max','lower','upper','length','substr','substring','coalesce','ifnull',
                   'nullif','round','like','glob','strftime','date','datetime','decimal_sum','decimal_neg'}
SQL_SPEC=schema({'sql':'string'},['sql'])


class DecimalSum:
    def __init__(self):self.total=money('0')
    def step(self,value):
        if value is not None:self.total+=money(value)
    def finalize(self):return str(self.total)


def read_sql(store,sql):
    if not isinstance(sql,str) or not sql.strip() or len(sql)>10000:
        raise ValueError('Provide a SQL query of at most 10,000 characters.')
    db=sqlite3.connect(':memory:')
    store.db.backup(db)
    db.create_aggregate('DECIMAL_SUM',1,DecimalSum)
    db.create_function('DECIMAL_NEG',1,lambda v:str(-money(v)) if v is not None else None)
    deadline=time.monotonic()+1.5
    def authorize(action,arg1,arg2,database,source):
        if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_RECURSIVE):return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_READ and arg1 in ALLOWED_TABLES:return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in ALLOWED_FUNCTIONS:return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    db.set_authorizer(authorize)
    db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
    try:
        cursor=db.execute(sql)
        if cursor.description is None:raise ValueError('Only read-only queries are allowed.')
        columns=[c[0] for c in cursor.description]
        records=cursor.fetchmany(1001)
        result={'sql':sql,'columns':columns,'rows':[list(r) for r in records[:1000]],
                'truncated':len(records)>1000,
                'money_note':'Money is decimal text. Use DECIMAL_SUM(amount) and DECIMAL_NEG(amount); SUM/AVG/TOTAL are disabled to avoid floating point totals.'}
        return result
    except (sqlite3.Error, sqlite3.Warning) as exc:
        raise ValueError(f'Read-only SQL rejected or failed: {exc}. Use allowed tables and DECIMAL_SUM for money.') from exc
    finally:
        db.close()


class WebTools(Tools):
    def definitions(self):
        return super().definitions()+[
            {'type':'function','function':{'name':'read_sql','description':
                'Run one bounded read-only SELECT on the active database scope. transactions has id,booking_date,month,amount (positive decimal text),currency,kind,category,person,household,merchant,tags. '
                'source_entries joins on transaction_id and has signed_booked,value_date,source_type (n26/garanti),account,card_id,section,bank_tag,bonus,original_amount,original_currency,exchange_rate,filename,sheet,source_row. '
                'Use DECIMAL_SUM(amount) for exact money aggregation, DECIMAL_NEG(amount) for refunds, COUNT(*) for rows; SUM/AVG are forbidden. '
                'No modifications, PRAGMA, filesystem, extensions, or arbitrary functions. Filter currency and explicit dates. Return row IDs when appropriate.',
                'parameters':SQL_SPEC}},
            {'type':'function','function':{'name':'data_inventory','description':'Get the active data scope, exact available dates, currencies, record counts, SQL schema and source types before querying.', 'parameters':schema({},[])}}]

    def call(self,name,arguments):
        if name=='read_sql':
            validate(arguments,SQL_SPEC)
            return read_sql(self.analysis.store,arguments['sql'])
        if name=='data_inventory':
            validate(arguments,schema({},[]))
            db=self.analysis.store.db
            return {'tables':{t:[{'name':r['name'],'type':r['type']} for r in db.execute(f'PRAGMA table_info("{t}")')] for t in sorted(ALLOWED_TABLES)},
                    'periods':[dict(r) for r in db.execute('SELECT currency,MIN(month) first_month,MAX(month) last_month,MIN(booking_date) first_booking_date,MAX(booking_date) last_booking_date,COUNT(*) records FROM transactions GROUP BY currency')],
                    'sources':[dict(r) for r in db.execute('SELECT source_type,COUNT(*) records FROM source_entries GROUP BY source_type')]}
        return super().call(name,arguments)
