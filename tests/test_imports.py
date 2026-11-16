import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from openpyxl import Workbook
from budget.importers import parse_file, tr_number, N26_COLUMNS
from budget.bank import initialize, duplicates, commit, preview_store, dashboard
from budget.store import Store
from budget.sql_tools import read_sql, WebTools
from budget.analysis import Analysis
from budget.web import create_app


def n26(rows=None,bom=False):
    rows=rows or [
        ['2026-11-04','2026-11-03','KAUFLAND BERLIN GESUND','','Presentment','','Main Account','-8.66','8.66','EUR','1'],
        ['2026-11-04','2026-11-04','SP THE BARN COFFEE','','Presentment','','Main Account','-5','5','EUR','1'],
        ['2026-11-04','2026-11-04','SP THE BARN COFFEE','','Presentment','','Main Account','-9.9','9.9','EUR','1']]
    out=io.StringIO(newline='');writer=csv.writer(out);writer.writerow(N26_COLUMNS);writer.writerows(rows)
    return (('\ufeff' if bom else '')+out.getvalue()).encode()


def garanti_rows():
    return [
        ['TL Account Summary Information For Card Number 5549 **** **** 0973'],
        [],['Date','Transaction','Tag','Bonus','Amount(TL)'],
        ['26/10/2026','BSKTEL10003567821OG202600 İSTANBUL','Payment','0,00','-190,00'],
        ['26/10/2026','OTOM. FATURA İŞLEM FAİZİ İSTANBUL','Payment','0,00','-5,56'],
        ['Date','Transaction','Tag','Bonus','Amount(TL)'],
        ['15/10/2026','OTOMATIK FATURA FAIZ IADE','Other','0,00','1,88'],
        ['09/10/2026','Cep Şube Ödeme','Card Payment','0,00','27.820,53'],
        ['21/10/2026','WL *STEAM PURCHASE BELLEVUE','Entertainment','2,50','-69,99'],
        ['EUR Account Summary Information For Card Number 5440 **** **** 8023'],
        ['Date','Transaction','Tag','Bonus','Amount(EUR)'],
        ['05/10/2026','Cep Şube Ödeme','Card Payment','0,00','145,60'],
        ['06/10/2026','A purchase','Other','0,00','-10,00'],
    ]


def xlsx_bytes(rows=None):
    book=Workbook();sheet=book.active;sheet.title='Statement'
    for row in rows or garanti_rows():sheet.append(row)
    out=io.BytesIO();book.save(out);book.close();return out.getvalue()


class BankTests(unittest.TestCase):
    def setUp(self):self.s=Store();initialize(self.s)
    def tearDown(self):self.s.db.close()
    def save(self,batches,edits=None):
        duplicates(self.s,batches)
        return commit(self.s,batches,edits or {})

    def test_n26_bom_signed_original_and_repeated_purchases(self):
        batch=parse_file('n26.csv',n26(bom=True));self.assertEqual(batch['errors'],[])
        self.assertEqual(self.save([batch]),3)
        r=dashboard(self.s)
        self.assertEqual(r['totals']['consumption'],'23.56')
        self.assertEqual(r['totals']['n26_net_account_movement'],'-23.56')
        row=dict(self.s.db.execute('SELECT * FROM source_entries ORDER BY transaction_id').fetchone())
        self.assertEqual(row['signed_booked'],'-8.66');self.assertEqual(row['value_date'],'2026-11-03')
        self.assertEqual(row['original_amount'],'8.66');self.assertEqual(row['transaction_type'],'Presentment')
        self.assertEqual(json.loads(row['raw_json'])['Partner Iban'],'')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM recurring').fetchone()[0],0)

    def test_positive_n26_is_unresolved_and_csv_quotes(self):
        data=n26([['2026-11-01','','Smith, Example','','Credit Transfer','note, "quoted"','Main Account','100','100','EUR','1']])
        batch=parse_file('income.csv',data);self.assertFalse(batch['errors'])
        self.assertEqual(batch['entries'][0]['kind'],'unresolved');self.save([batch])
        r=dashboard(self.s);self.assertEqual(r['totals']['unresolved'],'100');self.assertNotIn('income',r['totals'])
        self.assertEqual(r['transactions'][0]['merchant'],'Smith, Example')

    def test_invalid_csv_and_no_partial_commit(self):
        broken=n26()+b'not,a,valid,row\n'
        batch=parse_file('broken.csv',broken);self.assertTrue(batch['errors'])
        self.assertEqual(batch['errors'][0]['row'],5)
        with self.assertRaises(ValueError):self.save([batch])
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],0)
        self.assertTrue(parse_file('bad.csv',b'\xff\xfe')['errors'])
        self.assertTrue(parse_file('bad.csv',b'a,b\n1,2\n')['errors'])

    def test_garanti_multiple_sections_repeated_headers(self):
        batch=parse_file('disguised.xls',xlsx_bytes());self.assertEqual(batch['format'],'xlsx');self.assertEqual(batch['errors'],[])
        self.assertEqual(len(batch['entries']),7);self.save([batch])
        tr=dashboard(self.s,'TRY');eur=dashboard(self.s,'EUR')
        self.assertEqual(tr['totals']['consumption'],'263.67')
        self.assertEqual(tr['totals']['card_repayment'],'27820.53')
        self.assertEqual(eur['totals']['card_repayment'],'145.60');self.assertEqual(eur['totals']['consumption'],'10.00')
        cards={r[0] for r in self.s.db.execute('SELECT card_id FROM source_entries')}
        self.assertEqual(len(cards),2)
        bonus=self.s.db.execute("SELECT bonus FROM source_entries WHERE bank_tag='Entertainment'").fetchone()[0]
        self.assertEqual(bonus,'2.50')
        self.assertNotIn('n26_net_account_movement',tr['totals'])

    def test_real_legacy_xls_bytes(self):
        import xlwt
        book=xlwt.Workbook();sheet=book.add_sheet('Cards')
        for i,row in enumerate(garanti_rows()):
            for j,value in enumerate(row):sheet.write(i,j,value)
        buffer=io.BytesIO();book.save(buffer)
        batch=parse_file('wrong-extension.csv',buffer.getvalue())
        self.assertEqual(batch['format'],'xls');self.assertFalse(batch['errors']);self.assertEqual(len(batch['entries']),7)

    def test_workbook_missing_section_currency_mismatch_formula(self):
        rows=[['Date','Transaction','Tag','Bonus','Amount(EUR)'],['01/11/2026','x','Other','0','-1,00']]
        self.assertTrue(parse_file('no-section.xlsx',xlsx_bytes(rows))['errors'])
        rows=[['TL Account Summary Information For Card Number 1111 **** 1234'],['Date','Transaction','Tag','Bonus','Amount(EUR)'],['01/11/2026','x','Other','0','-1,00']]
        self.assertTrue(parse_file('mismatch.xlsx',xlsx_bytes(rows))['errors'])
        rows=[['EUR Account Summary Information For Card Number 1111 **** 1234'],['Date','Transaction','Tag','Bonus','Amount(EUR)'],['01/11/2026','x','Other','0','=1+2']]
        self.assertTrue(parse_file('formula.xlsx',xlsx_bytes(rows))['errors'])

    def test_idempotence_overlapping_export_and_repeated_identical_rows(self):
        original=parse_file('one.csv',n26());self.assertEqual(self.save([original]),3)
        again=parse_file('renamed.csv',n26());self.assertEqual(self.save([again]),0)
        overlap=parse_file('overlap.csv',n26()+b'\n');duplicates(self.s,[overlap])
        self.assertTrue(all(e['duplicate_candidates'] for e in overlap['entries']))
        with self.assertRaises(ValueError):commit(self.s,[overlap],{})
        edits={e['key']:{'decision':'skip'} for e in overlap['entries']}
        self.assertEqual(commit(self.s,[overlap],edits),0)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],3)
        one=['2026-12-01','','Coffee','','Presentment','','Main Account','-5','5','EUR','1']
        repeats=parse_file('legit.csv',n26([one,one]));duplicates(self.s,[repeats])
        self.assertTrue(repeats['entries'][1]['duplicate_candidates'])
        self.assertEqual(commit(self.s,[repeats],{repeats['entries'][1]['key']:{'decision':'keep'}}),2)

    def test_review_corrections_and_preview_never_saves(self):
        batch=parse_file('one.csv',n26());duplicates(self.s,[batch]);key=batch['entries'][0]['key']
        edits={key:{'category':'groceries','person':'Menekşe','booking_date':'2026-10-31','signed_booked':'-9.01','one_off':True}}
        preview=preview_store(self.s,[batch],edits)
        try:self.assertEqual(dashboard(preview)['totals']['consumption'],'23.91')
        finally:preview.db.close()
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],0)
        self.assertEqual(commit(self.s,[batch],edits),3)
        raw=self.s.db.execute('SELECT raw_json FROM source_entries ORDER BY transaction_id').fetchone()[0]
        self.assertEqual(json.loads(raw)['Amount (EUR)'],'-8.66')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],0)

    def test_decimal_sql_security_and_bounds(self):
        self.save([parse_file('a.csv',n26())])
        result=read_sql(self.s,'SELECT DECIMAL_SUM(amount) total FROM transactions')
        self.assertEqual(result['rows'],[['23.56']])
        for sql in ['DELETE FROM transactions','UPDATE transactions SET amount=0','PRAGMA database_list',"ATTACH DATABASE '/tmp/other.sqlite' AS other",'SELECT load_extension("evil")','SELECT randomblob(1000000000)','SELECT SUM(amount) FROM transactions','SELECT * FROM sqlite_master','SELECT 1; SELECT 2']:
            with self.assertRaises(ValueError,msg=sql):read_sql(self.s,sql)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],3)
        result=read_sql(self.s,'WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<2000) SELECT x FROM n')
        self.assertTrue(result['truncated']);self.assertEqual(len(result['rows']),1000)
        self.assertEqual(WebTools(Analysis(self.s)).call('read_sql',{'sql':'SELECT COUNT(*) FROM transactions'})['rows'],[[3]])


    def test_two_csv_months_and_separate_same_currency_cards(self):
        batches=[parse_file(p.name,p.read_bytes()) for p in sorted((Path(__file__).resolve().parents[1]/'examples').glob('n26-*.csv'))]
        self.assertEqual(self.save(batches),3)
        report=dashboard(self.s)
        self.assertEqual(report['totals']['consumption'],'57.25')
        self.assertEqual([r['n26_net_account_movement'] for r in report['monthly']],['-42.35','-14.90'])
        card_rows=[['EUR Account Summary Information For Card Number 1111 **** 1111'],
                   ['Date','Transaction','Tag','Bonus','Amount(EUR)'],['01/11/2026','Same merchant','Other',0,'-10,00'],
                   ['EUR Account Summary Information For Card Number 2222 **** 2222'],
                   ['Date','Transaction','Tag','Bonus','Amount(EUR)'],['01/11/2026','Same merchant','Other',0,'-10,00']]
        b=parse_file('cards.xlsx',xlsx_bytes(card_rows));duplicates(self.s,[b])
        self.assertFalse(any(e['duplicate_candidates'] for e in b['entries']))
        self.assertEqual(commit(self.s,[b],{}),2)
        self.assertEqual(len({e['card_id'] for e in b['entries']}),2)

    def test_html_disguised_as_xls_is_rejected(self):
        batch=parse_file('statement.xls',b'<html><table><tr><td>not xls</td></tr></table></html>')
        self.assertTrue(batch['errors'])
        self.assertIn('HTML/XML',batch['errors'][0]['message'])


    def test_chat_rejects_fake_execution_and_recovers_with_real_evidence(self):
        from budget.chat import Chat
        chat=Chat(WebTools(Analysis(self.s)),'test',require_evidence=True)
        responses=[{'role':'assistant','content':'SQL ran: invented total 2480.50'},
                   {'role':'assistant','tool_calls':[{'function':{'name':'read_sql','arguments':{'sql':'SELECT COUNT(*) FROM transactions'}}}]},
                   {'role':'assistant','content':'No recorded transactions.'}]
        with patch.object(chat,'_request',side_effect=responses):result=chat.ask('How much?')
        self.assertEqual(result['evidence'][0]['rows'],[[0]])
        self.assertNotIn('2480.50',json.dumps(chat.messages))
        chat=Chat(WebTools(Analysis(self.s)),'test',require_evidence=True)
        with patch.object(chat,'_request',return_value={'role':'assistant','content':'Unverified 100 EUR'}):
            with self.assertRaises(RuntimeError):chat.ask('How much?')


    def test_structured_sql_planner_validates_before_execution(self):
        from budget.chat import SQLChat
        chat=SQLChat(WebTools(Analysis(self.s)),'test')
        messages=[{'role':'assistant','content':json.dumps({'sql':'UPDATE transactions SET amount=0'})},
                  {'role':'assistant','content':json.dumps({'sql':'SELECT COUNT(*) FROM transactions'})},
                  {'role':'assistant','content':'There are no records.'}]
        with patch.object(chat,'_send',side_effect=messages) as send:
            result=chat.ask('Show records')
        self.assertIn('error',result['evidence'][0])
        self.assertEqual(result['evidence'][1]['rows'],[[0]])
        self.assertEqual(send.call_args_list[0].args[0]['format']['required'],['sql'])
        chat=SQLChat(WebTools(Analysis(self.s)),'test')
        with patch.object(chat,'_send',return_value={'role':'assistant','content':'Pretend SQL ran: 100 EUR'}):
            with self.assertRaises(RuntimeError):chat.ask('Show total')

    def test_numbers(self):
        self.assertEqual(str(tr_number('27.820,53')),'27820.53')
        self.assertEqual(str(tr_number('-69,99')),'-69.99')
        with self.assertRaises(ValueError):tr_number('27,820.53')


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'test.sqlite'
        self.client=TestClient(create_app(self.path));config=self.client.get('/api/config').json()
        self.headers={'X-Budget-Token':config['token']}
    def tearDown(self):self.client.close();self.temp.cleanup()
    def test_multi_upload_preview_sql_confirm_and_idempotence(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertIn('Start with your statements',self.client.get('/').text)
        files=[('files',('n26.csv',n26(),'text/csv')),('files',('card.xls',xlsx_bytes(),'application/octet-stream'))]
        result=self.client.post('/api/uploads',files=files,headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        preview=result.json();token=preview['preview_id']
        self.assertEqual(self.client.get('/api/dashboard').json()['record_count'],0)
        report=self.client.get('/api/dashboard',params={'scope':'uploads','preview_id':token}).json()
        self.assertEqual(report['record_count'],5)
        self.assertEqual(report['totals']['consumption'],'33.56')
        sql=self.client.post('/api/sql',headers=self.headers,json={'scope':'uploads','preview_id':token,'sql':'SELECT currency,COUNT(*) FROM transactions GROUP BY currency'})
        self.assertEqual(sql.status_code,200,sql.text);self.assertEqual(sql.json()['rows'],[['EUR',5],['TRY',5]])
        no=self.client.post(f'/api/confirm/{token}',headers=self.headers,json={});self.assertEqual(no.status_code,400)
        saved=self.client.post(f'/api/confirm/{token}',headers=self.headers,json={'confirmed':True});self.assertEqual(saved.json()['inserted'],10)
        self.assertEqual(self.client.get('/api/dashboard').json()['record_count'],5)
        again=self.client.post('/api/uploads',files=files,headers=self.headers).json()
        done=self.client.post('/api/confirm/'+again['preview_id'],headers=self.headers,json={'confirmed':True})
        self.assertEqual(done.json()['inserted'],0)

    def test_csrf_error_files_and_readonly_sql(self):
        self.assertEqual(self.client.post('/api/sql',json={'sql':'SELECT 1'}).status_code,403)
        bad=self.client.post('/api/uploads',files={'files':('bad.csv',b'bad','text/csv')},headers=self.headers).json()
        response=self.client.post('/api/confirm/'+bad['preview_id'],headers=self.headers,json={'confirmed':True})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.post('/api/sql',json={'sql':'DROP TABLE transactions'},headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/api/dashboard').json()['record_count'],0)

    def test_chat_tool_calls_use_selected_upload_scope(self):
        preview=self.client.post('/api/uploads',files={'files':('n26.csv',n26(),'text/csv')},headers=self.headers).json()
        responses=[{'role':'assistant','tool_calls':[{'function':{'name':'read_sql','arguments':{'sql':'SELECT DECIMAL_SUM(amount) FROM transactions'}}}]}, {'role':'assistant','content':'Recorded: 23.56 EUR'}]
        with patch('budget.chat.SQLChat._request',side_effect=responses):
            result=self.client.post('/api/chat',headers=self.headers,json={'scope':'uploads','preview_id':preview['preview_id'],'text':'Toplam?','language':'tr'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['evidence'][0]['rows'],[['23.56']])
        self.assertEqual(self.client.get('/api/dashboard').json()['record_count'],0)


if __name__=='__main__':unittest.main()
