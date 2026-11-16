import calendar
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation


def money(value):
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError("Money must be a decimal string, never a float")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal amount") from exc
    if not result.is_finite():
        raise ValueError("Amount must be finite")
    return result


def currency(value):
    if not isinstance(value, str) or len(value) != 3 or not value.isascii() or not value.isalpha() or value != value.upper():
        raise ValueError("Currency must be a three-letter uppercase code")
    return value


def month_bounds(month):
    start = date.fromisoformat(month + "-01")
    return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS categories(id TEXT PRIMARY KEY, parent TEXT REFERENCES categories(id));
        CREATE TABLE IF NOT EXISTS groups(name TEXT, category TEXT REFERENCES categories(id), PRIMARY KEY(name,category));
        CREATE TABLE IF NOT EXISTS transactions(
          id INTEGER PRIMARY KEY, booking_date TEXT, month TEXT NOT NULL, amount TEXT NOT NULL,
          currency TEXT NOT NULL, kind TEXT NOT NULL, category TEXT REFERENCES categories(id),
          person TEXT, household TEXT NOT NULL, merchant TEXT NOT NULL, tags TEXT NOT NULL,
          one_off INTEGER NOT NULL, recurring_id TEXT, source TEXT NOT NULL,
          CHECK(booking_date IS NOT NULL OR length(month)=7));
        CREATE TABLE IF NOT EXISTS coverage(
          household TEXT, currency TEXT, through_date TEXT, from_date TEXT,
          PRIMARY KEY(household,currency));
        CREATE TABLE IF NOT EXISTS recurring(
          id TEXT PRIMARY KEY, category TEXT REFERENCES categories(id), amount TEXT NOT NULL,
          currency TEXT NOT NULL, day INTEGER NOT NULL, person TEXT, household TEXT NOT NULL,
          start_month TEXT NOT NULL, end_month TEXT);
        CREATE TABLE IF NOT EXISTS plans(
          month TEXT, currency TEXT, household TEXT, income TEXT,
          PRIMARY KEY(month,currency,household));
        CREATE TABLE IF NOT EXISTS budgets(
          month TEXT, currency TEXT, household TEXT, category TEXT REFERENCES categories(id), amount TEXT,
          PRIMARY KEY(month,currency,household,category));
        ''')

    def category(self, name, parent=None):
        if not isinstance(name, str) or not name:
            raise ValueError("Category id required")
        ancestors = set()
        current = parent
        while current:
            if current == name or current in ancestors:
                raise ValueError("Category cycle")
            ancestors.add(current)
            row = self.db.execute("SELECT parent FROM categories WHERE id=?", (current,)).fetchone()
            if row is None:
                raise ValueError("Unknown parent")
            current = row[0]
        with self.db:
            self.db.execute("INSERT INTO categories VALUES (?,?) ON CONFLICT(id) DO UPDATE SET parent=excluded.parent", (name, parent))

    def group(self, name, categories):
        with self.db:
            self.db.execute("DELETE FROM groups WHERE name=?", (name,))
            self.db.executemany("INSERT INTO groups VALUES (?,?)", [(name, c) for c in set(categories)])

    def add(self, *, amount, currency_code, kind, category=None, booking_date=None,
            month=None, person=None, household="home", merchant="", tags=(), one_off=False,
            recurring_id=None, source="manual"):
        if kind not in {"expense", "refund", "income", "transfer", "card_repayment", "unresolved"}:
            raise ValueError("Invalid transaction kind")
        amount = money(amount)
        if amount < 0:
            raise ValueError("Use a positive magnitude and an explicit kind")
        if booking_date:
            parsed = date.fromisoformat(booking_date)
            if month and month != parsed.strftime("%Y-%m"):
                raise ValueError("Booking date and month disagree")
            month = parsed.strftime("%Y-%m")
        if not month:
            raise ValueError("Booking date or month required")
        month_bounds(month)
        if any("|" in tag for tag in tags):
            raise ValueError("Tags cannot contain |")
        with self.db:
            cursor = self.db.execute("""INSERT INTO transactions
              (booking_date,month,amount,currency,kind,category,person,household,merchant,tags,one_off,recurring_id,source)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (booking_date, month, str(amount), currency(currency_code), kind, category, person,
               household, merchant, "|".join(tags), int(one_off), recurring_id, source))
        return cursor.lastrowid

    def set_coverage(self, start, through, currency_code, household="home"):
        if date.fromisoformat(start) > date.fromisoformat(through):
            raise ValueError("Coverage start is after end")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO coverage VALUES (?,?,?,?)", (household, currency(currency_code), through, start))

    def confirm_recurring(self, id, category, amount, currency_code, day, start_month,
                          end_month=None, person=None, household="home"):
        if type(day) is not int or not 1 <= day <= 31 or money(amount) < 0:
            raise ValueError("Invalid recurring payment")
        month_bounds(start_month)
        if end_month:
            month_bounds(end_month)
            if end_month < start_month:
                raise ValueError("Invalid recurring interval")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO recurring VALUES (?,?,?,?,?,?,?,?,?)",
                (id, category, str(money(amount)), currency(currency_code), day, person, household, start_month, end_month))

    def set_income(self, month, amount, currency_code, household="home"):
        month_bounds(month)
        if money(amount) < 0:
            raise ValueError("Income must be nonnegative")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO plans VALUES (?,?,?,?)", (month, currency(currency_code), household, str(money(amount))))

    def set_budget(self, month, category, amount, currency_code, household="home"):
        month_bounds(month)
        if money(amount) < 0:
            raise ValueError("Budget must be nonnegative")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO budgets VALUES (?,?,?,?,?)", (month, currency(currency_code), household, category, str(money(amount))))
