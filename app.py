from functools import wraps
from flask import Flask, render_template, request, redirect, session
import os
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
DATABASE = os.environ.get("DATABASE_PATH", "expenses.db")

def get_db():
    return sqlite3.connect(DATABASE)

def login_required(route):
    @wraps(route)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return route(*args, **kwargs)
    return wrapper

# INIT DB
def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            amount REAL,
            note TEXT,
            date TEXT
        )
    ''')
    c.execute("PRAGMA table_info(expenses)")
    expense_columns = [column[1] for column in c.fetchall()]
    if "user_id" not in expense_columns:
        c.execute("ALTER TABLE expenses ADD COLUMN user_id INTEGER")

    today = datetime.now().strftime("%Y-%m-%d")
    c.execute(
        "UPDATE expenses SET date = ? WHERE date IS NULL OR date = ''",
        (today,)
    )
    conn.commit()
    conn.close()

init_db()

@app.route('/')
@login_required
def home():
    conn = get_db()
    c = conn.cursor()
    user_id = session["user_id"]

    c.execute(
        "SELECT id, category, amount, note, date FROM expenses WHERE user_id = ? ORDER BY category, id DESC",
        (user_id,)
    )
    expenses = c.fetchall()

    c.execute("SELECT SUM(amount) FROM expenses WHERE user_id = ?", (user_id,))
    total = c.fetchone()[0]
    if total is None:
        total = 0

    c.execute(
        "SELECT category, SUM(amount) FROM expenses WHERE user_id = ? GROUP BY category",
        (user_id,)
    )
    category_data = c.fetchall()

    categories = [row[0] for row in category_data]
    category_values = [row[1] for row in category_data]

    category_sections = []
    section_lookup = {}
    for expense in expenses:
        category = expense[1] if expense[1] else "Uncategorized"

        if category not in section_lookup:
            section_lookup[category] = {
                "name": category,
                "expenses": [],
                "total": 0
            }
            category_sections.append(section_lookup[category])

        section_lookup[category]["expenses"].append(expense)
        section_lookup[category]["total"] += expense[2] or 0

    # WEEKLY
    weekly_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekly_data = {}

    for expense in expenses:
        if not expense[4]:
            continue

        expense_date = datetime.strptime(expense[4], "%Y-%m-%d").date()
        week_start = expense_date - timedelta(days=expense_date.weekday())
        week_key = week_start.strftime("%Y-%m-%d")
        week_end = week_start + timedelta(days=6)
        day_index = expense_date.weekday()

        if week_key not in weekly_data:
            weekly_data[week_key] = {
                "title": f"{week_start.strftime('%d %b')} - {week_end.strftime('%d %b')}",
                "labels": weekly_labels,
                "values": [0, 0, 0, 0, 0, 0, 0]
            }

        weekly_data[week_key]["values"][day_index] += expense[2] or 0

    weekly_periods = sorted(weekly_data.keys())

    # MONTHLY
    c.execute("""
        SELECT substr(date, 1, 7) as month, SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY month
        ORDER BY month
    """, (user_id,))
    monthly_raw = c.fetchall()

    monthly_labels = [row[0] for row in monthly_raw]
    monthly_values = [row[1] for row in monthly_raw]

    c.execute("""
        SELECT substr(date, 1, 7) as month, substr(date, 9, 2) as day, SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY month, day
        ORDER BY month, day
    """, (user_id,))
    monthly_daily_raw = c.fetchall()

    monthly_daily_data = {}
    for month, day, amount in monthly_daily_raw:
        if month not in monthly_daily_data:
            monthly_daily_data[month] = {
                "labels": [],
                "values": []
            }

        monthly_daily_data[month]["labels"].append(day)
        monthly_daily_data[month]["values"].append(amount)

    c.execute("""
        SELECT substr(date, 1, 7) as month, category, SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY month, category
        ORDER BY month, category
    """, (user_id,))
    monthly_category_raw = c.fetchall()

    monthly_category_data = {}
    for month, category, amount in monthly_category_raw:
        if month not in monthly_category_data:
            monthly_category_data[month] = {
                "labels": [],
                "values": []
            }

        monthly_category_data[month]["labels"].append(category or "Uncategorized")
        monthly_category_data[month]["values"].append(amount)

    monthly_labels = monthly_labels if monthly_labels else []
    monthly_values = monthly_values if monthly_values else []

    categories = categories if categories else []
    category_values = category_values if category_values else []
    conn.close()

    return render_template(
        'index.html',
        expenses=expenses,
        total=total,
        categories=categories,
        category_values=category_values,
        category_totals=category_data,
        category_sections=category_sections,
        weekly_periods=weekly_periods,
        weekly_data=weekly_data,
        monthly_labels=monthly_labels,
        monthly_values=monthly_values,
        monthly_daily_data=monthly_daily_data,
        monthly_category_data=monthly_category_data,
        username=session.get("username")
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        if not username or not password:
            error = "Username and password are required."
        else:
            conn = get_db()
            c = conn.cursor()

            try:
                c.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password))
                )
                user_id = c.lastrowid
                conn.commit()
                session["user_id"] = user_id
                session["username"] = username
                return redirect("/")
            except sqlite3.IntegrityError:
                error = "Username already exists."
            finally:
                conn.close()

    return render_template("register.html", error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,)
        )
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["user_id"] = user[0]
            session["username"] = user[1]
            return redirect("/")

        error = "Invalid username or password."

    return render_template("login.html", error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect("/login")

# ADD
@app.route('/add', methods=['POST'])
@login_required
def add_expense():
    category = request.form['category']
    amount = request.form['amount']
    note = request.form['note']
    date = datetime.now().strftime("%Y-%m-%d")
    user_id = session["user_id"]

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO expenses (category, amount, note, date, user_id) VALUES (?, ?, ?, ?, ?)",
        (category, amount, note, date, user_id)
    )
    conn.commit()
    conn.close()

    return redirect('/')

# DELETE
@app.route('/delete/<int:id>')
@login_required
def delete_expense(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (id, session["user_id"]))
    conn.commit()
    conn.close()

    return redirect('/')

# RUN APP
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
