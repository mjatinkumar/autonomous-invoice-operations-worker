from __future__ import annotations

import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "invoices.db")))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            invoice_number TEXT NOT NULL,
            amount REAL NOT NULL,
            due_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS finance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL UNIQUE,
            amount REAL NOT NULL,
            due_date TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    seed_demo_data(conn)
    conn.close()


def seed_demo_data(conn: sqlite3.Connection | None = None) -> None:
    close_conn = conn is None
    if conn is None:
        conn = get_connection()

    invoice_count = conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    if invoice_count == 0:
        data = [
            ("Acme Corp", "INV-2026-001", 42000.0, "2026-01-18", "2026-01-10T09:00:00"),
            ("Acme Corp", "INV-2026-002", 63500.0, "2026-06-24", "2026-06-15T09:30:00"),
            ("Acme Corp", "INV-2026-003", 84500.0, "2026-10-20", "2026-10-01T11:45:00"),
            ("Acme Corp", "INV-2026-004", 56000.0, "2026-11-02", "2026-10-15T08:20:00"),
            ("Northwind", "INV-2026-101", 31000.0, "2026-02-05", "2026-01-15T13:00:00"),
            ("BluePeak", "INV-2026-205", 98000.0, "2026-08-14", "2026-08-02T10:10:00"),
        ]
        conn.executemany(
            "INSERT INTO invoices (company, invoice_number, amount, due_date, created_at) VALUES (?, ?, ?, ?, ?)",
            data,
        )

    finance_count = conn.execute("SELECT COUNT(*) FROM finance_records").fetchone()[0]
    if finance_count == 0:
        current = [
            ("INV-2026-001", 42000.0, "2026-01-18", "pending", "2026-01-11T09:00:00"),
            ("INV-2026-101", 31000.0, "2026-02-05", "posted", "2026-01-16T13:00:00"),
        ]
        conn.executemany(
            "INSERT INTO finance_records (invoice_number, amount, due_date, status, updated_at) VALUES (?, ?, ?, ?, ?)",
            current,
        )

    conn.commit()
    if close_conn:
        conn.close()


def reset_demo_data() -> None:
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM finance_records")
    conn.execute("DELETE FROM invoices")
    conn.commit()
    seed_demo_data(conn)
    conn.close()
