"""Optional browser integration test using synthetic files and a temporary database."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_imports import n26,xlsx_bytes


def main():
    artifacts=ROOT/'.local'/'qa';artifacts.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        log=open(Path(tmp)/'server.log','w')
        server=subprocess.Popen([sys.executable,'-m','budget','--db',str(Path(tmp)/'qa.sqlite'),'web','--port',str(port)],cwd=ROOT,stdout=log,stderr=log)
        base=f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                try:
                    with urlopen(base+'/api/config',timeout=1):break
                except Exception:time.sleep(.1)
            else:raise RuntimeError('QA server did not start')
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1512,'height':1100})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base);expect(page.locator('#database')).to_have_text('qa.sqlite')
                page.locator('#files').set_input_files([
                    {'name':'n26.csv','mimeType':'text/csv','buffer':n26(bom=True)},
                    {'name':'garanti.xls','mimeType':'application/octet-stream','buffer':xlsx_bytes()}])
                page.locator('#previewButton').click()
                expect(page.locator('#consumption')).to_contain_text('33.56')
                assert page.locator('#preview').is_visible()
                assert page.locator('.preview-file').count()==2
                category=page.locator('.preview-file').first.locator('tbody tr').first.locator('select').nth(1)
                category.select_option('groceries')
                page.get_by_role('button',name='Update analysis preview',exact=True).click()
                expect(page.locator('#groupChart')).to_contain_text('groceries')
                page.locator('#runSql').click()
                expect(page.locator('#sqlResult')).to_contain_text('23.56')
                page.locator('#sqlInput').fill('DELETE FROM transactions')
                page.locator('#runSql').click()
                page.locator('#sqlResult .error-box').wait_for()
                # Exercise the chat UI independently of model availability; backend model tool flow is unit-tested.
                page.route('**/api/chat',lambda route:route.fulfill(json={'answer':'Recorded consumption: 33.56 EUR','chat_id':'browser-smoke','evidence':[{'sql':'SELECT ...','rows':[['33.56']]}]}))
                page.locator('#chatInput').fill('Summarize my upload')
                page.locator('#sendChat').click()
                expect(page.locator('#chatMessages')).to_contain_text('Recorded consumption: 33.56 EUR')
                page.get_by_role('button',name='Confirm & save reviewed rows',exact=True).click()
                expect(page.locator('#notice')).to_contain_text('10 records saved')
                expect(page.locator('#scopeLabel')).to_contain_text('Database')
                page.locator('#groupBy').select_option('section')
                expect(page.locator('#groupChart')).to_contain_text('Main Account')
                page.locator('#year').select_option('2026')
                page.locator('#month').select_option('2026-11')
                expect(page.locator('#start')).to_have_value('2026-11-01')
                expect(page.locator('#end')).to_have_value('2026-11-30')
                expect(page.locator('#groupChart .pie-chart')).to_be_visible()
                expect(page.locator('#monthlyChart polyline')).to_have_count(2)
                page.locator('#monthlyChart circle').last.hover()
                expect(page.locator('#monthlyChart .chart-tooltip')).to_contain_text('Expenses')
                expect(page.locator('#transactionTable .expense-row').first).to_be_visible()
                page.locator('#chartCategory').select_option('groceries')
                expect(page.locator('#category')).to_have_value('groceries')
                expect(page.locator('#consumption')).to_contain_text('8.66')
                page.locator('#category').select_option('all')
                expect(page.locator('#chartCategory')).to_have_value('all')
                page.screenshot(path=str(artifacts/'dashboard-desktop.png'),full_page=True)
                page.locator('#language').click()
                page.get_by_role('heading',name='Paranıza daha geniş bir bakış.').wait_for()
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(artifacts/'dashboard-mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
                assert not errors,errors
                browser.close()
            print('Browser checks passed: multi-file preview, corrections, SQL totals/write rejection, chat evidence UI, confirmed import, section chart, EN/TR, mobile layout.')
            print('Screenshots:',artifacts)
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            log.close()


if __name__=='__main__':main()
