import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook
from budget.history import import_history
from budget.store import Store
from budget.bank import dashboard


class HistoryTests(unittest.TestCase):
    def test_literal_rows_refunds_provenance_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'ledger.xlsx'
            book = Workbook()
            sheet = book.active
            sheet.title = '04.26'
            for row in [['Gelirler','Euro'],['Salary',5000],['Sum','=SUM(B2:B2)'],
                        ['GIDERLER'],['market',100],['zalando refund',-25],
                        [None,30],['TOPLAM','=SUM(B5:B7)'],['Seyahat'],['hotel',200]]:
                sheet.append(row)
            sheet['F5'] = 200  # Side calculation is already in the main ledger.
            book.save(path)
            store = Store()
            try:
                result = import_history(store,path)
                self.assertEqual(result['inserted'],5)
                self.assertEqual(len(result['warnings']),1)
                report = dashboard(store,start='2026-01-01',end='2026-12-31')
                self.assertEqual(report['totals']['consumption'],'305')
                self.assertEqual(report['totals']['income'],'5000')
                self.assertTrue(all(r['booking_date'] is None for r in report['transactions']))
                self.assertTrue(all(r['sheet']=='04.26' for r in report['transactions']))
                category_report = dashboard(store,start='2026-04-01',end='2026-04-30',category='groceries')
                self.assertEqual(category_report['record_count'],1)
                self.assertEqual(category_report['totals']['consumption'],'100')
                self.assertEqual(category_report['category_totals'],[{'name':'groceries','amount':'100'}])
                self.assertEqual(import_history(store,path)['inserted'],0)
                self.assertEqual(dashboard(store,start='2026-04-02')['record_count'],0)
            finally:
                store.db.close()
