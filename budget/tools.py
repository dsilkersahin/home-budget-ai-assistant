"""Read-only tool boundary: no SQL, file access, budget writes or shell execution."""
from .analysis import resolve_period

FILTERS = {'household': 'string', 'person': 'string', 'categories': 'array',
           'exclude_categories': 'array', 'exclude_tags': 'array'}


def schema(properties, required):
    return {'type': 'object', 'properties': {
        k: {'type': v, **({'items': {'type': 'string'}} if v == 'array' else {})}
        for k, v in properties.items()}, 'required': required, 'additionalProperties': False}


PERIOD = {'currency_code': 'string', 'period': 'string', 'start': 'string', 'end': 'string', **FILTERS}
SPECS = {
    'spending_summary': ('Spending totals and monthly/category trends with supporting records. Default last_three_months means three completed calendar months.', schema(PERIOD, ['currency_code'])),
    'period_comparison': ('Compare complete calendar months to the equally long preceding period; contributors do not prove causes.', schema(PERIOD, ['currency_code'])),
    'transaction_drill_down': ('Show the records behind a total with the same filters.', schema(PERIOD, ['currency_code'])),
    'recurring_detection': ('Find repeated merchant/amount candidates. Candidates are never confirmed automatically.', schema(PERIOD, ['currency_code'])),
    'month_end_forecast': ('Experimental consumption projection; withhold without complete import coverage.', schema({'currency_code':'string','household':'string','person':'string'}, ['currency_code'])),
    'next_month_forecast': ('Experimental recent-average forecast with confirmed recurring payments.', schema({'currency_code':'string','household':'string','person':'string'}, ['currency_code'])),
    'scenario_simulation': ('Simulate upcoming expenses; never saves an approved budget.', {
        'type':'object', 'properties': {'currency_code':{'type':'string'}, 'household':{'type':'string'}, 'person':{'type':'string'},
        'mode':{'type':'string','enum':['month_end','next_month']}, 'savings_target':{'type':'string'},
        'additions':{'type':'array','items':{'type':'object','properties':{'category':{'type':'string'},'amount':{'type':'string'}},'required':['category','amount'],'additionalProperties':False}}},
        'required':['currency_code','additions'],'additionalProperties':False}),
    'baseline_backtest': ('Time-based baseline evaluation; requires complete history and outcomes.', schema({'start':'string','end':'string','currency_code':'string','household':'string'}, ['start','end','currency_code'])),
    'catalog': ('List available category/group ids, currencies, persons and asserted import coverage. Use before resolving names; ask if ambiguous.', schema({}, [])),
}


def validate(value, spec):
    expected = spec['type']
    if expected == 'object':
        if not isinstance(value, dict) or set(value)-set(spec['properties']) or set(spec.get('required', []))-set(value):
            raise ValueError('Invalid or missing tool arguments')
        for k, v in value.items():
            validate(v, spec['properties'][k])
    elif expected == 'array':
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError('Expected an array of at most 100 items')
        for v in value:
            validate(v, spec['items'])
    elif expected == 'string':
        if not isinstance(value, str) or not value or len(value) > 500:
            raise ValueError('Expected a nonempty string of at most 500 characters')
    if 'enum' in spec and value not in spec['enum']:
        raise ValueError('Unsupported value')


class Tools:
    def __init__(self, analysis):
        self.analysis = analysis
        self.context = {}

    def definitions(self):
        return [{'type':'function','function':{'name':k,'description':v[0],'parameters':v[1]}} for k,v in SPECS.items()]

    def call(self, name, arguments):
        if name not in SPECS:
            raise ValueError('Unknown tool')
        validate(arguments, SPECS[name][1])
        args = dict(arguments)
        a = self.analysis
        if name == 'catalog':
            return {table: [dict(r) for r in a.store.db.execute(query)] for table, query in {
                'categories':'SELECT * FROM categories', 'groups':'SELECT * FROM groups',
                'coverage':'SELECT * FROM coverage',
                'currencies':'SELECT DISTINCT currency FROM transactions',
                'people':'SELECT DISTINCT person FROM transactions WHERE person IS NOT NULL'}.items()}
        if name == 'baseline_backtest':
            return a.backtest(**args)
        if name in {'month_end_forecast','next_month_forecast','scenario_simulation'}:
            if name == 'scenario_simulation':
                return a.scenario(**args)
            return a.forecast(**args, mode='month_end' if name == 'month_end_forecast' else 'next_month')
        # Session-scoped inheritance makes drill-down and filter-only follow-ups exact.
        merged = {**self.context, **args}
        if 'period' in args:
            merged.pop('start', None)
            merged.pop('end', None)
        elif 'start' in args or 'end' in args:
            if not {'start','end'} <= set(args):
                raise ValueError('Explicit start and end must be supplied together')
            merged.pop('period', None)
        period = merged.pop('period', 'last_three_months')
        if 'start' in merged:
            start, end = merged.pop('start'), merged.pop('end')
        else:
            start, end = [d.isoformat() for d in resolve_period(period, a.today)]
        currency_code = merged.pop('currency_code')
        if name == 'period_comparison':
            result = a.compare(start, end, currency_code, **merged)
        elif name == 'recurring_detection':
            result = {'start':start,'end':end,'currency':currency_code,'candidates':a.recurring_candidates(start,end,currency_code,**merged),
                      'coverage':a.coverage(start,end,currency_code,merged.get('household','home'))}
        else:
            result = a.summarize(start,end,currency_code,**merged)
        self.context = {**merged,'start':start,'end':end,'currency_code':currency_code}
        return result
