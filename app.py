from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from functools import wraps
import re


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "SAMUE_CHANGE_THIS_SECRET_KEY"
)

DATABASE = None


class DBConnection:
    def __init__(self, conn):
        self.conn = conn
        self.postgres = True

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(sql, params)
        return cursor

    def executemany(self, sql, params):
        sql = sql.replace("?", "%s")
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.executemany(sql, params)
        return cursor

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://", "postgresql://", 1
        )

    return DBConnection(psycopg2.connect(database_url))

def init_db():
    conn = get_db()

    # Create the application tables if they do not already exist.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            fullname TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            balance DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            reward DOUBLE PRECISION NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS completed_tasks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, task_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            account_name TEXT NOT NULL,
            account_number TEXT NOT NULL,
            bank_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Repair columns that may be missing from an older PostgreSQL schema.
    migrations = [
        ("users", "fullname", "TEXT"),
        ("users", "email", "TEXT"),
        ("users", "password", "TEXT"),
        ("users", "balance", "DOUBLE PRECISION DEFAULT 0"),
        ("users", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("tasks", "title", "TEXT"),
        ("tasks", "description", "TEXT"),
        ("tasks", "reward", "DOUBLE PRECISION DEFAULT 0"),
        ("tasks", "active", "INTEGER DEFAULT 1"),
        ("completed_tasks", "user_id", "INTEGER"),
        ("completed_tasks", "task_id", "INTEGER"),
        ("completed_tasks", "completed_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("withdrawals", "user_id", "INTEGER"),
        ("withdrawals", "amount", "DOUBLE PRECISION DEFAULT 0"),
        ("withdrawals", "account_name", "TEXT"),
        ("withdrawals", "account_number", "TEXT"),
        ("withdrawals", "bank_name", "TEXT"),
        ("withdrawals", "status", "TEXT DEFAULT 'Pending'"),
        ("withdrawals", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    ]

    for table, column, definition in migrations:
        conn.execute(
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {definition}'
        )

    # Keep existing users intact while ensuring NULL balances do not
    # break dashboard and withdrawal calculations.
    conn.execute("""
        UPDATE users
        SET balance = 0
        WHERE balance IS NULL
    """)

    task_count = conn.execute(
        "SELECT COUNT(*) AS count FROM tasks"
    ).fetchone()["count"]

    if task_count == 0:
        conn.executemany("""
            INSERT INTO tasks (title, description, reward)
            VALUES (?, ?, ?)
        """, [
            (
                "Website Visit",
                "Visit the assigned website and complete the required activity.",
                50
            ),
            (
                "Social Media Task",
                "Complete the assigned social media engagement task.",
                100
            ),
            (
                "Survey Task",
                "Complete the available survey accurately.",
                150
            ),
            (
                "Content Review",
                "Read and review the assigned content.",
                75
            ),
            (
                "Daily Check-in",
                "Complete your daily platform check-in.",
                25
            )
        ])

    conn.commit()
    conn.close()

def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to continue.", "error")
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_user():
    if "user_id" not in session:
        return {"current_user": None}

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    conn.close()

    return {"current_user": user}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not fullname or not email or not password or not confirm_password:
            flash("Please complete every field.")
            return redirect(url_for("signup"))

        email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

        if not re.match(email_pattern, email):
            flash("Please enter a valid email address.")
            return redirect(url_for("signup"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect(url_for("signup"))

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("signup"))

        conn = get_db()

        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if existing:
            conn.close()
            flash("That email is already registered.")
            return redirect(url_for("login"))

        hashed_password = generate_password_hash(password)

        conn.execute("""
            INSERT INTO users (fullname, email, password)
            VALUES (?, ?, ?)
        """, (
            fullname,
            email,
            hashed_password
        ))

        conn.commit()
        conn.close()

        flash("Account created successfully. Please login.")

        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        conn.close()

        if user:
            stored_password = user["password"]

            try:
                password_valid = check_password_hash(
                    stored_password,
                    password
                )
            except (ValueError, TypeError):
                password_valid = stored_password == password

            if password_valid:
                session["user_id"] = user["id"]
                return redirect(url_for("dashboard"))

        flash("Incorrect email or password.")

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    tasks = conn.execute("""
        SELECT
            tasks.*,
            CASE
                WHEN completed_tasks.id IS NULL THEN 0
                ELSE 1
            END AS completed
        FROM tasks
        LEFT JOIN completed_tasks
        ON tasks.id = completed_tasks.task_id
        AND completed_tasks.user_id = ?
        WHERE tasks.active = 1
        ORDER BY tasks.id DESC
    """, (session["user_id"],)).fetchall()

    completed_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM completed_tasks
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()["count"]

    conn.close()

    return render_template(
        "dashboard.html",
        user=user,
        tasks=tasks,
        completed_count=completed_count
    )


@app.route("/complete-task/<int:task_id>", methods=["POST"])
@login_required
def complete_task(task_id):

    conn = get_db()

    task = conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND active = 1",
        (task_id,)
    ).fetchone()

    if not task:
        conn.close()
        flash("Task not found.")
        return redirect(url_for("dashboard"))

    already_completed = conn.execute("""
        SELECT id
        FROM completed_tasks
        WHERE user_id = ? AND task_id = ?
    """, (
        session["user_id"],
        task_id
    )).fetchone()

    if already_completed:
        conn.close()
        flash("You have already completed this task.")
        return redirect(url_for("dashboard"))

    conn.execute("""
        INSERT INTO completed_tasks (user_id, task_id)
        VALUES (?, ?)
    """, (
        session["user_id"],
        task_id
    ))

    conn.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE id = ?
    """, (
        task["reward"],
        session["user_id"]
    ))

    conn.commit()
    conn.close()

    flash(f"Task completed! ₦{task['reward']:,.2f} has been added to your balance.")

    return redirect(url_for("dashboard"))


@app.route("/deposit")
@login_required
def deposit():
    return render_template("deposit.html")


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():

    if request.method == "POST":

        amount_text = request.form.get("amount", "").strip()
        account_name = request.form.get("account_name", "").strip()
        account_number = request.form.get("account_number", "").strip()
        bank_name = request.form.get("bank_name", "").strip()

        try:
            amount = float(amount_text)
        except ValueError:
            flash("Enter a valid withdrawal amount.")
            return redirect(url_for("withdraw"))

        if amount <= 0:
            flash("Withdrawal amount must be greater than zero.")
            return redirect(url_for("withdraw"))

        if not account_name or not account_number or not bank_name:
            flash("Please complete all bank details.")
            return redirect(url_for("withdraw"))

        conn = get_db()

        user = conn.execute(
            "SELECT balance FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()

        if amount > user["balance"]:
            conn.close()
            flash("Insufficient balance.")
            return redirect(url_for("withdraw"))

        conn.execute("""
            UPDATE users
            SET balance = balance - ?
            WHERE id = ?
        """, (
            amount,
            session["user_id"]
        ))

        conn.execute("""
            INSERT INTO withdrawals
            (
                user_id,
                amount,
                account_name,
                account_number,
                bank_name
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            session["user_id"],
            amount,
            account_name,
            account_number,
            bank_name
        ))

        conn.commit()
        conn.close()

        flash(
            "Withdrawal request submitted successfully. "
            "It is currently pending review."
        )

        return redirect(url_for("dashboard"))

    return render_template("withdraw.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))
ADMIN_PIN = "martins_pass_2026"


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        pin = request.form.get("pin", "")

        if pin == ADMIN_PIN:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))

        flash("Incorrect admin PIN.")

    return render_template("admin_login.html")


@app.route("/admin")
def admin_dashboard():

    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    conn = get_db()

    users = conn.execute("""
        SELECT
            id,
            fullname,
            email,
            balance,
            created_at
        FROM users
        ORDER BY id DESC
    """).fetchall()

    total_users = conn.execute(
        "SELECT COUNT(*) AS count FROM users"
    ).fetchone()["count"]

    total_balance = conn.execute(
        "SELECT COALESCE(SUM(balance), 0) AS total FROM users"
    ).fetchone()["total"]

    conn.close()

    return render_template(
        "admin.html",
        users=users,
        total_users=total_users,
        total_balance=total_balance
    )


@app.route("/admin-logout")
def admin_logout():

    session.pop("admin_logged_in", None)

    return redirect(url_for("index"))

# Initialize the database when the application starts.
# This is required for both local Flask and Render/Gunicorn.
init_db()

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
