from __future__ import annotations

import os
from datetime import datetime

from app.database import get_connection

UPDATE_FAILURE_STATE = {"attempts": 0}


def reset_update_failure_state() -> None:
    UPDATE_FAILURE_STATE["attempts"] = 0


def _parse_date(value: str) -> datetime:
    for candidate in (value, f"{value}T00:00:00"):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return datetime.min


def search_invoices(company: str) -> dict:
    query = (company or "").strip()
    if not query:
        return {"success": False, "error": "Company name is required", "invoices": []}

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE lower(company) = lower(?) ORDER BY created_at DESC",
            (query,),
        ).fetchall()

    return {
        "success": True,
        "company": query,
        "invoices": [dict(row) for row in rows],
        "count": len(rows),
    }


def get_invoice(invoice_id: int | str) -> dict:
    invoice_id_value = int(invoice_id)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id_value,)).fetchone()

    if row is None:
        return {"success": False, "error": f"Invoice {invoice_id_value} not found", "invoice": None}

    return {"success": True, "invoice": dict(row)}


def update_finance_record(invoice_number: str, amount: float, due_date: str, approval_token: str | None = None) -> dict:
    require_approval = os.getenv("REQUIRE_APPROVAL", "false").lower() in {"1", "true", "yes"}
    if require_approval and not approval_token:
        return {
            "success": False,
            "error": "Approval required before finance updates.",
            "retryable": False,
            "requires_approval": True,
        }

    UPDATE_FAILURE_STATE["attempts"] += 1
    if UPDATE_FAILURE_STATE["attempts"] == 1:
        return {
            "success": False,
            "error": "Temporary finance system unavailable",
            "retryable": True,
            "invoice_number": invoice_number,
            "amount": amount,
            "due_date": due_date,
        }

    with get_connection() as conn:
        record = conn.execute(
            "SELECT * FROM finance_records WHERE invoice_number = ?",
            (invoice_number,),
        ).fetchone()

        if record is None:
            conn.execute(
                "INSERT INTO finance_records (invoice_number, amount, due_date, status, updated_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (invoice_number, float(amount), due_date, "posted"),
            )
        else:
            conn.execute(
                "UPDATE finance_records SET amount = ?, due_date = ?, status = 'posted', updated_at = datetime('now') WHERE invoice_number = ?",
                (float(amount), due_date, invoice_number),
            )

        conn.commit()
        updated = conn.execute(
            "SELECT * FROM finance_records WHERE invoice_number = ?",
            (invoice_number,),
        ).fetchone()

    return {
        "success": True,
        "status": "posted",
        "invoice_number": invoice_number,
        "finance_record": dict(updated),
    }


def verify_finance_record(invoice_number: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM finance_records WHERE invoice_number = ?",
            (invoice_number,),
        ).fetchone()

    if row is None:
        return {"success": False, "error": f"Finance record for {invoice_number} not found", "record": None}

    payload = dict(row)
    return {
        "success": True,
        "invoice_number": invoice_number,
        "record": payload,
        "matches": True,
    }


def latest_invoice_for_company(company: str) -> dict | None:
    company_name = (company or "").strip()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE lower(company) = lower(?) ORDER BY created_at DESC",
            (company_name,),
        ).fetchall()
    if not rows:
        return None
    latest = max(rows, key=lambda row: _parse_date(row["created_at"]))
    return dict(latest)
