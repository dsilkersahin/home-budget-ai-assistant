import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from .store import money, currency, month_bounds

ZERO = Decimal(0)


def shift_month(month, offset):
    d, _ = month_bounds(month)
    n = d.year * 12 + d.month - 1 + offset
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def resolve_period(period="last_three_months", today=None):
    today = today or date.today()
    month = today.strftime("%Y-%m")
    if period == "last_three_months":
        return month_bounds(shift_month(month, -3))[0], month_bounds(shift_month(month, -1))[1]
    if period == "previous_three_months":
        return month_bounds(shift_month(month, -6))[0], month_bounds(shift_month(month, -4))[1]
    if period == "current_plus_two":
        return month_bounds(shift_month(month, -2))[0], today
    if period == "rolling_three_months":
        target, end = month_bounds(shift_month(month, -3))
        return target.replace(day=min(today.day, end.day)) + timedelta(days=1), today
    if period == "last_month":
        return month_bounds(shift_month(month, -1))
    if period == "current_month":
        return month_bounds(month)[0], today
    raise ValueError("Unknown period")


class Analysis:
    def __init__(self, store, today=None):
        self.store = store
        self.today = today or date.today()

    def expand(self, categories):
        if categories is None:
            return None
        found = set()
        all_cats = {r['id']: r['parent'] for r in self.store.db.execute("SELECT * FROM categories")}
        for c in categories:
            group = [r[0] for r in self.store.db.execute("SELECT category FROM groups WHERE name=?", (c,))]
            if c not in all_cats and not group:
                raise ValueError(f"Unknown category or group: {c}")
            found.update(group or [c])
        while True:
            children = {c for c, p in all_cats.items() if p in found}
            if children <= found:
                return found
            found |= children

    def rows(self, start, end, currency_code, household="home", person=None,
             categories=None, exclude_categories=None, exclude_tags=None):
        start, end = date.fromisoformat(start), date.fromisoformat(end)
        if start > end:
            raise ValueError("Start is after end")
        include = self.expand(categories)
        exclude = self.expand(exclude_categories) or set()
        result, partial_months = [], set()
        for raw in self.store.db.execute("SELECT * FROM transactions WHERE currency=? AND household=? ORDER BY month,booking_date,id", (currency(currency_code), household)):
            r = dict(raw)
            if person is not None and r['person'] != person:
                continue
            if include is not None and r['category'] not in include or r['category'] in exclude:
                continue
            if set(r['tags'].split('|')) & set(exclude_tags or []):
                continue
            if r['booking_date']:
                if not start <= date.fromisoformat(r['booking_date']) <= end:
                    continue
            else:
                first, last = month_bounds(r['month'])
                if last < start or first > end:
                    continue
                if first < start or last > end:
                    partial_months.add(r['month'])
                    continue
            result.append(r)
        return result, sorted(partial_months)

    def coverage(self, start, end, currency_code, household="home"):
        row = self.store.db.execute("SELECT * FROM coverage WHERE household=? AND currency=?", (household, currency_code)).fetchone()
        return {"from": row['from_date'] if row else None, "through": row['through_date'] if row else None,
                "complete": bool(row and row['from_date'] <= start and row['through_date'] >= end)}

    def summarize(self, start, end, currency_code, **filters):
        rows, partial = self.rows(start, end, currency_code, **filters)
        monthly, category_totals = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
        monthly_categories = defaultdict(lambda: defaultdict(lambda: ZERO))
        m = start[:7]
        while m <= end[:7]:
            monthly[m] = ZERO
            m = shift_month(m, 1)
        totals = {k: ZERO for k in ['expense', 'refund', 'income', 'transfer', 'card_repayment', 'unresolved']}
        for r in rows:
            amount = money(r['amount'])
            totals[r['kind']] += amount
            if r['kind'] in {'expense', 'refund'}:
                net = amount if r['kind'] == 'expense' else -amount
                monthly[r['month']] += net
                category_totals[r['category'] or 'uncategorized'] += net
                monthly_categories[r['month']][r['category'] or 'uncategorized'] += net
        spending = totals['expense'] - totals['refund']
        coverage = self.coverage(start, end, currency_code, filters.get('household', 'home'))
        limitations = []
        if not coverage['complete']:
            limitations.append('Import completeness is unknown or does not cover the requested period; absent records are not zero spending.')
        if partial:
            limitations.append('Monthly aggregates excluded from partial months: ' + ', '.join(partial))
        if totals['unresolved']:
            limitations.append('Unresolved entries are excluded from spending and known cash flow.')
        return {"start": start, "end": end, "currency": currency_code, "filters": filters,
                "consumption": str(spending), "monthly": {m: str(v) for m, v in monthly.items()},
                "monthly_average": str(spending / len(monthly)),
                "monthly_categories": {m: {c: str(v) for c,v in monthly_categories[m].items()} for m in monthly},
                "categories": {c: str(v) for c, v in category_totals.items()},
                "card_repayments": str(totals['card_repayment']),
                "income": str(totals['income']),
                "known_net_cash_flow": None,
                "cash_flow_note": "Withheld: account-level cash movements and card settlement timing are not modeled yet. Do not add card purchases and repayments as cash expenses.",
                "coverage": coverage, "limitations": limitations, "transactions": rows}

    def compare(self, start, end, currency_code, **filters):
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        count = (last.year-first.year)*12 + last.month-first.month + 1
        if first.day != 1 or last != month_bounds(end[:7])[1]:
            raise ValueError("Comparison requires complete calendar months")
        previous_end = first - timedelta(days=1)
        previous_start = month_bounds(shift_month(start[:7], -count))[0]
        current = self.summarize(start, end, currency_code, **filters)
        previous = self.summarize(previous_start.isoformat(), previous_end.isoformat(), currency_code, **filters)
        delta = money(current['consumption']) - money(previous['consumption'])
        old = money(previous['consumption'])
        changes = {c: str(money(current['categories'].get(c, '0'))-money(previous['categories'].get(c, '0')))
                   for c in current['categories'].keys() | previous['categories'].keys()}
        return {"current": current, "previous": previous, "change": str(delta),
                "percent_change": str(delta / old * 100) if old > 0 else None,
                "category_changes": changes,
                "explanation_limit": "Changes identify recorded contributors, not causes; inspect supporting transactions."}

    def recurring_candidates(self, start, end, currency_code, **filters):
        rows, _ = self.rows(start, end, currency_code, **filters)
        groups = defaultdict(list)
        for r in rows:
            if r['kind'] == 'expense' and not r['one_off'] and r['merchant'] and r['booking_date']:
                groups[(r['merchant'], r['category'], r['person'], r['amount'])].append(r)
        return [{"merchant": k[0], "category": k[1], "person": k[2], "amount": k[3],
                 "transaction_ids": [r['id'] for r in v], "status": "candidate_requires_confirmation"}
                for k, v in groups.items() if len({r['month'] for r in v}) >= 2]

    def forecast(self, currency_code, mode="next_month", household="home", person=None):
        currency(currency_code)
        if mode not in {'next_month', 'month_end'}:
            raise ValueError("Unknown forecast mode")
        current = self.today.strftime('%Y-%m')
        target = shift_month(current, 1) if mode == 'next_month' else current
        hist_start = month_bounds(shift_month(current, -3))[0].isoformat()
        hist_end = month_bounds(shift_month(current, -1))[1].isoformat()
        required_end = self.today.isoformat() if mode == 'month_end' else hist_end
        coverage = self.coverage(hist_start, required_end, currency_code, household)
        base = {"type": "forecast", "mode": mode, "month": target, "currency": currency_code,
                "coverage": coverage, "history_start": hist_start, "history_end": hist_end}
        if not coverage['complete']:
            return {**base, "status": "withheld", "reason": "Confirm complete imports for the entire required period before forecasting."}
        filters = {"household": household, "person": person}
        history, _ = self.rows(hist_start, hist_end, currency_code, **filters)
        recurring = [dict(r) for r in self.store.db.execute("SELECT * FROM recurring WHERE currency=? AND household=? AND start_month<=? AND (end_month IS NULL OR end_month>=?)", (currency_code, household, target, target)) if person is None or r['person'] == person]
        confirmed_payments = [dict(r) for r in self.store.db.execute("SELECT * FROM recurring WHERE currency=? AND household=?", (currency_code, household))]
        confirmed_ids = {r['id'] for r in confirmed_payments}
        if any(r['kind'] == 'unresolved' for r in history):
            return {**base, 'status':'withheld', 'reason':'Resolve unclassified historical entries before forecasting.'}
        if any(r['kind'] == 'expense' and not r['recurring_id'] and any(
            p['category'] == r['category'] and money(p['amount']) == money(r['amount']) and p['person'] == r['person']
            for p in confirmed_payments) for r in history):
            return {**base, 'status':'withheld', 'reason':'Link possible historical recurring payments before forecasting to avoid double counting.'}
        routine = defaultdict(lambda: ZERO)
        excluded = ZERO
        for r in history:
            if r['kind'] not in {'expense', 'refund'}:
                continue
            net = money(r['amount']) * (1 if r['kind'] == 'expense' else -1)
            if r['one_off'] or r['category'] == 'travel' or 'travel' in r['tags'].split('|'):
                excluded += net
            elif r['recurring_id'] not in confirmed_ids:
                routine[r['category'] or 'uncategorized'] += net / 3
        actual = defaultdict(lambda: ZERO)
        variable_actual = defaultdict(lambda: ZERO)
        known = defaultdict(lambda: ZERO)
        uncertainty = []
        actual_rows = []
        if mode == 'month_end':
            actual_rows, partial = self.rows(target+'-01', self.today.isoformat(), currency_code, **filters)
            if any(r['kind'] == 'unresolved' for r in actual_rows):
                return {**base, 'status':'withheld', 'reason':'Resolve unclassified current-month entries before forecasting.'}
            if partial:
                return {**base, "status": "withheld", "reason": "Monthly-only aggregates cannot support a daily current-month projection."}
            for r in actual_rows:
                if r['kind'] in {'expense', 'refund'}:
                    net = money(r['amount']) * (1 if r['kind'] == 'expense' else -1)
                    c = r['category'] or 'uncategorized'
                    actual[c] += net
                    if not r['one_off'] and r['category'] != 'travel' and 'travel' not in r['tags'].split('|') and r['recurring_id'] not in confirmed_ids:
                        variable_actual[c] += net
        for payment in recurring:
            if any(r['recurring_id'] == payment['id'] and r['kind'] == 'expense' for r in actual_rows):
                continue
            # An unlinked plausible match is ambiguous: withhold instead of counting twice.
            if any(r['kind'] == 'expense' and r['category'] == payment['category'] and money(r['amount']) == money(payment['amount']) and r['person'] == payment['person'] for r in actual_rows):
                uncertainty.append(payment['id'])
                continue
            known[payment['category'] or 'uncategorized'] += money(payment['amount'])
        if uncertainty:
            return {**base, "status": "withheld", "reason": "Resolve possible recorded recurring-payment matches.", "recurring_ids": uncertainty}
        days = calendar.monthrange(self.today.year, self.today.month)[1]
        estimates = {}
        for c in routine.keys() | actual.keys() | known.keys():
            remaining = max(ZERO, routine[c]) if mode == 'next_month' else max(ZERO, variable_actual[c]) / self.today.day * (days - self.today.day)
            estimates[c] = {"actual": str(actual[c]), "known_remaining": str(known[c]),
                            "estimated_variable": str(remaining), "total": str(actual[c]+known[c]+remaining)}
        total = sum((money(v['total']) for v in estimates.values()), ZERO)
        income = self.store.db.execute("SELECT income FROM plans WHERE month=? AND currency=? AND household=?", (target, currency_code, household)).fetchone() if person is None else None
        budgets = {r['category']: money(r['amount']) for r in self.store.db.execute("SELECT * FROM budgets WHERE month=? AND currency=? AND household=?", (target, currency_code, household))} if person is None else {}
        return {**base, "status": "estimated", "categories": estimates, "total": str(total),
                "expected_income": income[0] if income else None,
                "surplus": str(money(income[0])-total) if income else None,
                "over_budget": [c for c in budgets if c in estimates and money(estimates[c]['total']) > budgets[c]],
                "excluded_historical_one_off_travel": str(excluded),
                "assumptions": ["Three completed months, arithmetic category mean for next month; current month uses recorded routine daily pace.",
                    "Confirmed monthly payments require recurring_id links on recorded purchases; overdue unrecorded payments remain expected.",
                    "Travel and flagged one-offs are excluded from routine history. Add upcoming expenses through scenarios.",
                    "Consumption forecast excludes card repayments and transfers; surplus is income minus consumption, not available bank cash.",
                    "No statistically calibrated uncertainty interval. Import coverage is a user assertion.",
                    "A zero daily pace is only used after explicit confirmation that imports are complete through today."],
                "supporting_transaction_ids": [r['id'] for r in history+actual_rows]}

    def scenario(self, currency_code, additions, mode='next_month', savings_target=None, **filters):
        forecast = self.forecast(currency_code, mode, **filters)
        if forecast['status'] != 'estimated':
            return forecast
        changes = defaultdict(lambda: ZERO)
        for entry in additions:
            if set(entry) != {'category', 'amount'}:
                raise ValueError("Scenario entries need category and amount")
            self.expand([entry['category']])
            if money(entry['amount']) < 0:
                raise ValueError("Upcoming expenses must be nonnegative")
            changes[entry['category']] += money(entry['amount'])
        total = money(forecast['total']) + sum(changes.values(), ZERO)
        surplus = money(forecast['expected_income'])-total if forecast['expected_income'] is not None else None
        target = money(savings_target) if savings_target is not None else None
        if target is not None and target < 0:
            raise ValueError("Savings target must be nonnegative")
        return {"type": "scenario", "baseline": forecast, "additions": {k: str(v) for k,v in changes.items()},
                "total": str(total), "surplus": str(surplus) if surplus is not None else None,
                "savings_target": str(target) if target is not None else None,
                "additional_savings_needed": str(max(ZERO,target-surplus)) if target is not None and surplus is not None else None,
                "saved_as_budget": False}

    def backtest(self, start, end, currency_code, household='home'):
        first, last = month_bounds(start)[0], month_bounds(end)[1]
        if first > last:
            raise ValueError('Invalid backtest interval')
        results = []
        month = start
        while month <= end:
            hs = month_bounds(shift_month(month,-3))[0].isoformat()
            he = month_bounds(month)[1].isoformat()
            if not self.coverage(hs,he,currency_code,household)['complete']:
                raise ValueError('Backtest requires complete history and outcome coverage')
            totals = [money(self.summarize(*[d.isoformat() for d in month_bounds(shift_month(month,i))],currency_code,household=household)['consumption']) for i in (-3,-2,-1)]
            actual = money(self.summarize(month+'-01',he,currency_code,household=household)['consumption'])
            results.append({'month':month,'actual':str(actual),'mean':str(sum(totals,ZERO)/3), 'median':str(median(totals)), 'last_month':str(totals[-1])})
            month = shift_month(month,1)
        return {'folds':results,'mae':{k:str(sum((abs(money(r[k])-money(r['actual'])) for r in results),ZERO)/len(results)) for k in ('mean','median','last_month')},
                'limitation':'Expanding time-ordered baseline evaluation only; not an evaluation of recurring-adjusted forecasts. No calibrated intervals.'}
