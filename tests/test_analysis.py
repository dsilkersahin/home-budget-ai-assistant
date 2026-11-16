import json
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from budget.store import Store, money
from budget.analysis import Analysis, resolve_period
from budget.tools import Tools
from budget.chat import Chat


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.s = Store()
        for c,p in [('shopping',None),('clothing','shopping'),('electronics','shopping'),('groceries',None),('entertainment',None),('travel',None),('rent',None)]:
            self.s.category(c,p)
        self.s.group('shopping_group',['shopping','clothing','electronics'])
        self.a = Analysis(self.s,date(2026,11,12))
        self.t = Tools(self.a)

    def tearDown(self):
        self.s.db.close()

    def add(self, amount='10', month='2026-10', **kw):
        return self.s.add(amount=amount,month=month,currency_code=kw.pop('currency_code','EUR'),kind=kw.pop('kind','expense'),category=kw.pop('category','groceries'),**kw)

    def cover(self, through='2026-11-12'):
        self.s.set_coverage('2026-01-01',through,'EUR')

    def test_periods(self):
        for period, expected in [('last_three_months',('2026-08-01','2026-10-31')),('current_plus_two',('2026-09-01','2026-11-12')),('rolling_three_months',('2026-08-13','2026-11-12'))]:
            self.assertEqual(tuple(d.isoformat() for d in resolve_period(period,self.a.today)),expected)
        self.assertEqual(resolve_period('last_three_months',date(2026,1,10))[0],date(2025,10,1))
        self.assertEqual(resolve_period('last_month',date(2024,3,1))[1],date(2024,2,29))

    def test_decimal_and_currency_separation(self):
        self.add('0.1');self.add('0.2');self.add('100',currency_code='TRY')
        self.assertEqual(self.t.call('spending_summary',{'currency_code':'EUR'})['consumption'],'0.3')
        for v in [0.1,'NaN','Infinity',True]:
            with self.assertRaises(ValueError): money(v)

    def test_groups_refunds_and_cash_flow(self):
        self.add('100',category='clothing');self.add('25',category='electronics')
        self.add('5',category='clothing',kind='refund')
        self.add('120',kind='card_repayment');self.add('900',kind='income');self.add('50',kind='transfer')
        r=self.t.call('spending_summary',{'currency_code':'EUR','categories':['shopping','shopping_group','clothing']})
        self.assertEqual(r['consumption'],'120')
        self.assertEqual(len(r['transactions']),3)
        r=self.t.call('spending_summary',{'currency_code':'EUR','categories':[]})
        self.assertEqual(r['consumption'],'0')
        r=self.a.summarize('2026-08-01','2026-10-31','EUR')
        self.assertEqual(r['card_repayments'],'120')
        self.assertIsNone(r['known_net_cash_flow'])

    def test_person_and_follow_up(self):
        self.add(person='Menekşe');self.add(person='İlker');self.add(category='travel',person='Menekşe')
        self.t.call('spending_summary',{'currency_code':'EUR'})
        r=self.t.call('transaction_drill_down',{'currency_code':'EUR','person':'Menekşe','exclude_categories':['travel']})
        self.assertEqual(r['consumption'],'10')
        self.assertEqual(r['start'],'2026-08-01')
        self.assertEqual(self.t.call('transaction_drill_down',{'currency_code':'EUR'})['consumption'],'10')

    def test_comparison_and_monthly_categories(self):
        self.add('30',month='2026-07');self.add('90',month='2026-10',category='clothing')
        r=self.t.call('period_comparison',{'currency_code':'EUR'})
        self.assertEqual(r['change'],'60')
        self.assertEqual(r['previous']['start'],'2026-05-01')
        self.assertEqual(r['current']['monthly_categories']['2026-10']['clothing'],'90')
        self.assertIn('not causes',r['explanation_limit'])

    def test_partial_month_aggregates_not_invented(self):
        self.add('300',month='2026-11')
        r=self.a.summarize('2026-11-01','2026-11-12','EUR')
        self.assertEqual(r['consumption'],'0')
        self.assertTrue(any('Monthly aggregates' in x for x in r['limitations']))
        self.cover()
        self.assertEqual(self.a.forecast('EUR','month_end')['status'],'withheld')

    def test_forecast_coverage_and_reconciliation(self):
        self.assertEqual(self.a.forecast('EUR')['status'],'withheld')
        for month in ['2026-08','2026-09','2026-10']:
            self.add('300',month=month)
            self.add('500',month=month,category='rent',recurring_id='rent')
            self.add('900',month=month,category='travel')
            self.add('100',month=month,category='electronics',one_off=True)
        self.s.confirm_recurring('rent','rent','500','EUR',1,'2026-01')
        self.s.set_income('2026-12','1200','EUR')
        self.s.set_budget('2026-12','groceries','250','EUR')
        self.cover()
        r=self.a.forecast('EUR')
        self.assertEqual(Decimal(r['total']),Decimal('800'))
        self.assertEqual(Decimal(r['surplus']),Decimal('400'))
        self.assertEqual(sum(Decimal(v['total']) for v in r['categories'].values()),Decimal(r['total']))
        self.assertEqual(r['over_budget'],['groceries'])
        scenario=self.a.scenario('EUR',[{'category':'travel','amount':'600'}],savings_target='500')
        self.assertEqual(Decimal(scenario['total']),Decimal('1400'))
        self.assertEqual(Decimal(scenario['additional_savings_needed']),Decimal('700'))
        self.assertFalse(scenario['saved_as_budget'])
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM budgets').fetchone()[0],1)

    def test_month_end_does_not_double_count_recurring(self):
        self.cover()
        self.s.confirm_recurring('rent','rent','500','EUR',1,'2026-01')
        self.add('500',booking_date='2026-11-01',month='2026-11',category='rent',recurring_id='rent')
        self.add('120',booking_date='2026-11-12',month='2026-11')
        self.add('500',booking_date='2026-11-02',month='2026-11',kind='card_repayment')
        r=self.a.forecast('EUR','month_end')
        self.assertEqual(Decimal(r['total']),Decimal('800'))
        self.assertEqual(r['categories']['rent']['known_remaining'],'0')
        self.assertEqual(Decimal(r['categories']['groceries']['estimated_variable']),Decimal('180'))

    def test_ambiguous_recurring_and_unresolved_withhold(self):
        self.cover()
        self.s.confirm_recurring('rent','rent','500.0','EUR',1,'2026-01')
        self.add('500',booking_date='2026-11-01',month='2026-11',category='rent')
        self.assertEqual(self.a.forecast('EUR','month_end')['status'],'withheld')
        self.add('12',kind='unresolved')
        self.assertEqual(self.a.forecast('EUR')['status'],'withheld')

    def test_recurring_candidates_are_not_confirmed(self):
        self.add('20',month='2026-09',booking_date='2026-09-05',merchant='Service')
        self.add('20',month='2026-10',booking_date='2026-10-05',merchant='Service')
        r=self.t.call('recurring_detection',{'currency_code':'EUR'})
        self.assertEqual(r['candidates'][0]['status'],'candidate_requires_confirmation')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM recurring').fetchone()[0],0)

    def test_validation(self):
        for name,args in [('sql',{}),('spending_summary',{'currency_code':'EUR','sql':'DROP TABLE transactions'}),('spending_summary',{'currency_code':3}),('spending_summary',{'currency_code':'EUR','start':'2026-01-01'}),('spending_summary',{'currency_code':'EUR','categories':['fake']})]:
            with self.assertRaises(ValueError):self.t.call(name,args)
        with self.assertRaises(ValueError):self.s.category('shopping','clothing')
        with self.assertRaises(ValueError):self.add(month='2026-09',booking_date='2026-10-01')

    def test_backtest_time_order(self):
        self.cover('2026-10-31')
        for m,a in [('2026-07','30'),('2026-08','60'),('2026-09','90'),('2026-10','120')]:self.add(a,month=m)
        r=self.a.backtest('2026-10','2026-10','EUR')
        self.assertEqual(r['folds'][0]['mean'],'60')
        self.assertEqual(r['mae']['last_month'],'30')
        self.assertEqual(r['mae']['mean'],'60')

    def test_bilingual_chat_tool_loop_and_evidence(self):
        self.add('15',category='clothing')
        for text in ['How much did we spend shopping in the last three months?','Son üç ayda alışverişe ne kadar harcadık?']:
            chat=Chat(self.t,'test-model')
            messages=[{'role':'assistant','tool_calls':[{'function':{'name':'spending_summary','arguments':{'currency_code':'EUR','categories':['shopping_group']}}}]},{'role':'assistant','content':'2026-08-01 – 2026-10-31: 15 EUR'}]
            with patch.object(chat,'_request',side_effect=messages):r=chat.ask(text)
            self.assertEqual(r['evidence'][0]['consumption'],'15')
            self.assertTrue(r['evidence'][0]['limitations'])

    def test_tool_loop_is_bounded(self):
        chat=Chat(self.t,'test-model')
        message={'role':'assistant','tool_calls':[{'function':{'name':'catalog','arguments':{}}}]}
        with patch.object(chat,'_request',return_value=message):
            with self.assertRaises(RuntimeError):chat.ask('test')


if __name__ == '__main__':unittest.main()
