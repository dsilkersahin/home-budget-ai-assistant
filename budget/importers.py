"""Deterministic bank parsers. Parsing never writes to the application database."""
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePath
from .store import money

MAX_BYTES = 15 * 1024 * 1024
MAX_ROWS = 15000
N26_COLUMNS = ['Booking Date', 'Value Date', 'Partner Name', 'Partner Iban', 'Type',
               'Payment Reference', 'Account Name', 'Amount (EUR)', 'Original Amount',
               'Original Currency', 'Exchange Rate']
CATEGORY_IDS = ['groceries','household_supplies','coffee','eating_out','socializing',
                'housing','utilities','transport','subscriptions','health','pets','travel',
                'activities','electronics','clothing','education','shopping','insurance',
                'donations','savings','income','entertainment','uncategorized']
KINDS = {'expense','refund','income','transfer','card_repayment','unresolved'}


def tr_number(value):
    if isinstance(value, (int, float, Decimal)):
        # Spreadsheet numeric cells arrive as floats; recover their decimal text once.
        return money(str(value))
    text = str(value or '').strip().replace('\u00a0', '').replace(' ', '')
    if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?',text):
        raise ValueError(f'Invalid Turkish amount: {value!r}')
    return money(text.replace('.', '').replace(',', '.'))


def parse_date(value, turkish=False):
    if isinstance(value,(datetime,date)):
        return value.date().isoformat() if isinstance(value,datetime) else value.isoformat()
    text = str(value or '').strip()
    try:
        return datetime.strptime(text,'%d/%m/%Y').date().isoformat() if turkish else date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f'Invalid date: {text!r}') from exc


def entry(batch, row, *, booking_date, amount, merchant, currency_code, kind,
          sheet='', account='', section='', **metadata):
    return {'key':f"{batch['digest']}:{sheet}:{row}", 'booking_date':booking_date,
            'value_date':None,'month':booking_date[:7], 'amount':str(abs(amount)),
            'signed_booked':str(amount), 'currency':currency_code, 'kind':kind,
            'category':'uncategorized', 'person':None, 'merchant':str(merchant or ''),
            'source_type':batch['source_type'], 'filename':batch['filename'],
            'sheet':sheet, 'row':row, 'account':account, 'section':section,
            'card_id':None, 'bank_tag':'', 'bonus':None, 'original_amount':None,
            'original_currency':None, 'exchange_rate':None, 'payment_reference':'',
            'transaction_type':'', 'partner_iban':'', 'warnings':[], 'raw':{}, **metadata}


def parse_n26(batch, data):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('N26 CSV must be UTF-8 (BOM is supported).') from exc
    reader = csv.DictReader(io.StringIO(text,newline=''),strict=True)
    if reader.fieldnames != N26_COLUMNS:
        # Column order may differ; repeated or missing column names are ambiguous.
        if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or set(reader.fieldnames)!=set(N26_COLUMNS):
            raise ValueError('N26 CSV headers do not match the expected 11 columns.')
    for index, raw in enumerate(reader,1):
        if index > MAX_ROWS:
            raise ValueError('Too many rows; split this export into smaller files.')
        row_number = reader.line_num
        try:
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError('Wrong column count')
            amount = money(raw['Amount (EUR)'].strip())
            original = money(raw['Original Amount'].strip()) if raw['Original Amount'].strip() else None
            rate = money(raw['Exchange Rate'].strip()) if raw['Exchange Rate'].strip() else None
            if rate is not None and rate <= 0:
                raise ValueError('Exchange rate must be positive')
            orig_currency=raw['Original Currency'].strip()
            if orig_currency and not re.fullmatch('[A-Z]{3}',orig_currency):
                raise ValueError('Invalid original currency')
            kind = 'expense' if amount < 0 and raw['Type'].strip().casefold() == 'presentment' else 'unresolved'
            warnings=['Category is unreviewed.']
            if kind == 'unresolved':
                warnings.append('Review classification: positive amounts are not automatically income; transfers and card settlements are not consumption.')
            item = entry(batch,row_number,booking_date=parse_date(raw['Booking Date']),amount=amount,
                merchant=raw['Partner Name'],currency_code='EUR',kind=kind,
                value_date=parse_date(raw['Value Date']) if raw['Value Date'].strip() else None,
                account=raw['Account Name'],section=raw['Account Name'] or 'N26',
                original_amount=str(original) if original is not None else None,
                original_currency=orig_currency or None,exchange_rate=str(rate) if rate is not None else None,
                payment_reference=raw['Payment Reference'],transaction_type=raw['Type'],
                partner_iban=raw['Partner Iban'],raw=raw,warnings=warnings)
            batch['entries'].append(item)
        except ValueError as exc:
            batch['errors'].append({'sheet':'','row':row_number,'message':str(exc),'raw':raw})


SECTION = re.compile(r'\b(TL|TRY|EUR)\s+Account Summary Information For Card Number\s+(.+)', re.I)


def workbook_sheets(data, file_format):
    if file_format == 'xlsx':
        from openpyxl import load_workbook
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Expanded workbook exceeds 100 MB.')
        book=load_workbook(io.BytesIO(data),read_only=True,data_only=False)
        try:
            for sheet in book:
                if sheet.max_column and sheet.max_column > 200:
                    raise ValueError('Workbook has more than 200 columns.')
                yield sheet.title, sheet.iter_rows(values_only=True)
        finally:
            book.close()
    else:
        import xlrd
        book=xlrd.open_workbook(file_contents=data,on_demand=True)
        try:
            for sheet in book.sheets():
                if sheet.ncols > 200:
                    raise ValueError('Workbook has more than 200 columns.')
                def rows(sheet=sheet):
                    for n in range(sheet.nrows):
                        result=[]
                        for cell in sheet.row(n):
                            result.append(xlrd.xldate_as_datetime(cell.value,book.datemode) if cell.ctype==xlrd.XL_CELL_DATE else cell.value)
                        yield result
                yield sheet.name, rows()
        finally:
            book.release_resources()


def parse_garanti(batch,data,file_format):
    total_rows=0
    for sheet,rows in workbook_sheets(data,file_format):
        section=None
        headers=None
        for n,values in enumerate(rows,1):
            total_rows+=1
            if total_rows>MAX_ROWS:
                raise ValueError('Too many workbook rows; split this file.')
            values=list(values)
            texts=[str(v or '').strip() for v in values]
            if not any(texts):
                continue
            heading=next((SECTION.search(t) for t in texts if SECTION.search(t)),None)
            if heading:
                section={'currency':'TRY' if heading[1].upper() in {'TL','TRY'} else 'EUR',
                         'card_id':heading[2].strip(),'label':heading[0]}
                headers=None
                continue
            if 'Date' in texts and 'Transaction' in texts:
                headers={t:i for i,t in enumerate(texts) if t}
                amount_headers=[t for t in texts if re.fullmatch(r'Amount\((TL|TRY|EUR)\)',t)]
                if not section or len(amount_headers)!=1:
                    batch['errors'].append({'sheet':sheet,'row':n,'message':'Table has no unambiguous card/currency section.'})
                    headers=None
                    continue
                header_currency='TRY' if amount_headers[0] in {'Amount(TL)','Amount(TRY)'} else 'EUR'
                if header_currency!=section['currency'] or not {'Tag','Bonus'} <= set(headers):
                    batch['errors'].append({'sheet':sheet,'row':n,'message':'Section/header currency mismatch or missing Tag/Bonus columns.'})
                    headers=None
                    continue
                headers['__amount']=headers[amount_headers[0]]
                continue
            if any(t.casefold() in {'total','subtotal','toplam','ara toplam','genel toplam'} for t in texts) and not any(re.fullmatch(r'\d{2}/\d{2}/\d{4}',t) for t in texts):
                continue
            if not headers:
                if any(re.fullmatch(r'\d{2}/\d{2}/\d{4}',t) for t in texts):
                    batch['errors'].append({'sheet':sheet,'row':n,'message':'Dated row outside a valid card table; review section/header.'})
                continue
            def get(column):
                i=headers[column]
                return values[i] if i<len(values) else None
            raw={k:str(get(k)) if get(k) is not None else '' for k in headers if not k.startswith('__')}
            # Notes/headings after a table are not purchases. Amount-bearing malformed rows are errors.
            if not get('Date') and not get('__amount'):
                continue
            if str(get('Date') or '').startswith('=') or str(get('__amount') or '').startswith('='):
                batch['errors'].append({'sheet':sheet,'row':n,'message':'Formula in transaction fields; export values before importing.','raw':raw})
                continue
            if not get('Date') and not re.search(r'\d',str(get('__amount') or '')):
                continue
            try:
                amount=tr_number(get('__amount'))
                tag=str(get('Tag') or '')
                description=str(get('Transaction') or '')
                repayment=tag.casefold()=='card payment' or 'cep şube ödeme' in description.casefold()
                kind=('card_repayment' if amount>0 else 'unresolved') if repayment else 'expense' if amount<0 else 'unresolved'
                warnings=['Category is unreviewed.']
                if repayment:
                    warnings.append('Suggested card repayment; excluded from consumption. Confirm in preview.')
                elif amount>0:
                    kind='refund' if ('iade' in description.casefold() or 'refund' in tag.casefold()) else 'unresolved'
                    warnings.append('Positive card entry: review suggested refund/unresolved classification; never assumed income.')
                category={'entertainment':'entertainment','travel':'travel'}.get(tag.casefold(),'uncategorized')
                batch['entries'].append(entry(batch,n,sheet=sheet,booking_date=parse_date(get('Date'),True),
                    amount=amount,merchant=description,currency_code=section['currency'],kind=kind,
                    account=section['card_id'],card_id=section['card_id'],section=section['label'],
                    bank_tag=tag,bonus=str(tr_number(get('Bonus'))) if get('Bonus') not in (None,'') else None,
                    category=category,raw=raw,warnings=warnings))
            except ValueError as exc:
                batch['errors'].append({'sheet':sheet,'row':n,'message':str(exc),'raw':raw})


def parse_file(filename,data):
    if not data or len(data)>MAX_BYTES:
        raise ValueError('File must contain between 1 byte and 15 MB.')
    # Check bytes, never infer the workbook format from its extension.
    fmt='xlsx' if data.startswith(b'PK\x03\x04') else 'xls' if data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1') else 'csv'
    batch={'filename':PurePath(filename.replace('\\','/')).name,'digest':hashlib.sha256(data).hexdigest(),
           'format':fmt,'source_type':'n26' if fmt=='csv' else 'garanti','entries':[],'errors':[]}
    try:
        if data.lstrip().lower().startswith((b'<!doctype html',b'<html',b'<table',b'<?xml')):
            raise ValueError('This is an HTML/XML export, not a genuine XLS/XLSX workbook or N26 CSV. Re-export as XLS/XLSX.')
        if fmt=='csv':
            parse_n26(batch,data)
        else:
            parse_garanti(batch,data,fmt)
    except Exception as exc:
        batch['errors'].append({'sheet':'','row':None,'message':f'{type(exc).__name__}: {exc}'})
    if not batch['entries'] and not batch['errors']:
        batch['errors'].append({'sheet':'','row':None,'message':'No transaction rows found. Expected N26 CSV or Garanti card sections.'})
    return batch
