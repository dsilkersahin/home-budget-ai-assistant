"""Import monthly household ledgers without inventing booking dates."""
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from .bank import initialize, insert_row
from .importers import entry


def category_for(label, section):
    text = label.casefold()
    rules = {
        'housing': ('kira',),
        'insurance': ('sigorta',),
        'utilities': ('elektrik', 'internet', 'vodafone', 'radyo', 'radio'),
        'subscriptions': ('prime', 'primw', 'chatgpt', 'apple'),
        'groceries': ('market',),
        'household_supplies': ('dm', 'rossman', 'ikea', 'obi', 'hali', 'kitaplik'),
        'health': ('eczane', 'dermotoloji', 'kozmetik'),
        'pets': ('porsuk',),
        'education': ('kurs', 'english', 'ingilizce', 'preply', 'class'),
        'transport': ('ulasim', 'uber', 'miles', 'db ticket'),
        'clothing': ('zalando', 'mango', 'uniqlo', 'vinted', 'ayakkabi', 'hm ', 'zara', 'decathlon'),
        'activities': ('spor', 'usc', 'padel', 'studyo', 'strata', 'davul'),
        'eating_out': ('yemek',),
        'socializing': ('out',),
        'entertainment': ('bilet', 'konser', 'opera', 'lotto', 'loto'),
        'shopping': ('amazon', 'amazin', 'temu'),
    }
    if section == 'travel':
        return 'travel'
    if section == 'activities':
        return 'activities'
    for category, words in rules.items():
        if any(word in text for word in words):
            return category
    return 'uncategorized'


def import_history(store, filename):
    from openpyxl import load_workbook
    path = Path(filename)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    initialize(store)
    if store.db.execute('SELECT 1 FROM import_batches WHERE digest=?', (digest,)).fetchone():
        return {'inserted': 0, 'already_imported': True}
    batch = {'digest': digest, 'filename': path.name, 'source_type': 'historical'}
    rows = []
    warnings = []
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        for sheet in book:
            match = re.fullmatch(r'(\d{2})\.(\d{2})', sheet.title)
            if not match:
                raise ValueError(f'Unsupported monthly sheet: {sheet.title}')
            month = f'20{match[2]}-{match[1]}'
            section = None
            for number, values in enumerate(sheet.values, 1):
                if not values:
                    continue
                label = str(values[0] or '').strip()
                value = values[1] if len(values) > 1 else None
                text = label.casefold()
                if text == 'gelirler': section = 'income'
                elif text == 'giderler': section = 'expenses'
                elif text == 'seyahat': section = 'travel'
                elif text == 'etkinlik': section = 'activities'
                elif text == 'extra': section = 'extra'
                # Only literal ledger amounts in column B. Side calculations and
                # formula totals repeat amounts already represented in the ledger.
                if section is None or not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                amount = Decimal(str(value))
                kind = 'income' if section == 'income' else 'refund' if amount < 0 else 'expense'
                category = 'income' if kind == 'income' else category_for(label, section)
                if not label:
                    warnings.append(f'{sheet.title}!B{number}: unlabeled amount {amount}; imported as uncategorized.')
                item = entry(batch, number, booking_date=month+'-01', amount=amount if kind == 'income' else -amount,
                             merchant=label or 'Unlabeled ledger entry', currency_code='EUR', kind=kind,
                             sheet=sheet.title, section=section, category=category,
                             raw={'label': label, 'amount': str(amount), 'notes': str(values[2] or '') if len(values)>2 else ''})
                item['booking_date'] = None
                rows.append(item)
    finally:
        book.close()
    if not rows:
        raise ValueError('No monthly ledger amounts found.')
    with store.db:
        batch_id = store.db.execute('INSERT INTO import_batches(digest,filename,source_type,file_format) VALUES (?,?,?,?)',
                                    (digest, path.name, 'historical', 'xlsx')).lastrowid
        for row in rows:
            insert_row(store.db, batch_id, row)
    return {'inserted': len(rows), 'months': sorted({r['month'] for r in rows}), 'warnings': warnings}
