from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import uuid
from typing import Any, Optional

from .config import settings


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(settings.DISPUTE_DB_PATH)), exist_ok=True)
    c = sqlite3.connect(settings.DISPUTE_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_dispute_db() -> None:
    conn = _conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS dispute_tickets (
                ticket_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                transaction_id TEXT NOT NULL,
                submitted_by_email TEXT NOT NULL,
                dispute_category TEXT NOT NULL,
                customer_narrative TEXT NOT NULL,
                customer_evidence TEXT DEFAULT '',
                status TEXT NOT NULL,
                assigned_reason_code TEXT DEFAULT '',
                provisional_credit_cents INTEGER DEFAULT 0,
                network_filing_id TEXT DEFAULT '',
                agent_summary TEXT DEFAULT '',
                customer_response_draft TEXT DEFAULT '',
                processing_latency_ms REAL DEFAULT 0,
                trace_id TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_steps (
                step_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                step_number INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                tool_name TEXT DEFAULT '',
                input_payload TEXT DEFAULT '',
                output_payload TEXT DEFAULT '',
                latency_ms REAL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
        _seed_initial_tickets(conn)
    finally:
        conn.close()


def _seed_initial_tickets(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM dispute_tickets")
    if cur.fetchone()["cnt"] > 0:
        return

    now = datetime.now(timezone.utc)
    queued = [
        (
            "DSP-44010",
            "ACCT-1001",
            "TXN-9001",
            "treasury@apexlogistics.example",
            "UNAUTHORIZED_FRAUD",
            "We noticed an unrecognized online charge of $1,420.50 at ElectroMart Global on our corporate card. None of our logistics managers authorized this purchase and we have signed a fraud declaration.",
            "Signed corporate cardholder fraud affidavit ref #AF-2026-881",
            "QUEUED_FOR_TRIAGE",
            "",
            0,
            "",
            "",
            "",
            0.0,
            "",
            (now - timedelta(hours=5)).isoformat(),
            (now - timedelta(hours=5)).isoformat(),
        ),
        (
            "DSP-44011",
            "ACCT-1001",
            "TXN-9002",
            "treasury@apexlogistics.example",
            "MERCHANT_DISPUTE",
            "CloudScale Analytics billed us $890.00 for annual seat renewal even though our VP told their account rep on a call last month we did not plan to renew. Please credit our account right away.",
            "No written cancellation email yet; verbal conversation on phone.",
            "QUEUED_FOR_TRIAGE",
            "",
            0,
            "",
            "",
            "",
            0.0,
            "",
            (now - timedelta(hours=3)).isoformat(),
            (now - timedelta(hours=3)).isoformat(),
        ),
        (
            "DSP-44012",
            "ACCT-2004",
            "TXN-9003",
            "finance@harborviewbakery.example",
            "DUPLICATE_CHARGE",
            "Pacific Restaurant Supply swiped our card twice at the terminal on the same afternoon for $185.75 (see TXN-9003 and TXN-9003A). Requesting immediate provisional credit under Reg E.",
            "Terminal receipt batch #1 and batch #2 showing identical $185.75 charges.",
            "QUEUED_FOR_TRIAGE",
            "",
            0,
            "",
            "",
            "",
            0.0,
            "",
            (now - timedelta(hours=2)).isoformat(),
            (now - timedelta(hours=2)).isoformat(),
        ),
        (
            "DSP-44013",
            "ACCT-3002",
            "TXN-9004",
            "ap@northstarmfg.example",
            "ACH_UNAUTHORIZED",
            "Metro Industrial Leasing pulled an unauthorized $3,400.00 corporate ACH debit from our operating account five days ago without an active lease schedule.",
            "Master lease termination schedule #ML-992",
            "QUEUED_FOR_TRIAGE",
            "",
            0,
            "",
            "",
            "",
            0.0,
            "",
            (now - timedelta(hours=1)).isoformat(),
            (now - timedelta(hours=1)).isoformat(),
        ),
    ]
    cur.executemany(
        """
        INSERT INTO dispute_tickets (
            ticket_id, account_id, transaction_id, submitted_by_email,
            dispute_category, customer_narrative, customer_evidence, status,
            assigned_reason_code, provisional_credit_cents, network_filing_id,
            agent_summary, customer_response_draft, processing_latency_ms,
            trace_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        queued,
    )
    conn.commit()


def create_ticket(
    account_id: str,
    transaction_id: str,
    submitted_by_email: str,
    dispute_category: str,
    customer_narrative: str,
    customer_evidence: str = "",
) -> dict[str, Any]:
    ticket_id = f"DSP-{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    conn = _conn()
    try:
        conn.execute(
            """
            INSERT INTO dispute_tickets (
                ticket_id, account_id, transaction_id, submitted_by_email,
                dispute_category, customer_narrative, customer_evidence,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'TRIAGING', ?, ?)
            """,
            (
                ticket_id,
                account_id,
                transaction_id,
                submitted_by_email,
                dispute_category,
                customer_narrative,
                customer_evidence,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_ticket(ticket_id)  # type: ignore[return-value]


def update_ticket_resolution(
    ticket_id: str,
    status: str,
    assigned_reason_code: str,
    provisional_credit_cents: int,
    network_filing_id: str,
    agent_summary: str,
    customer_response_draft: str,
    processing_latency_ms: float,
    trace_id: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = _conn()
    try:
        conn.execute(
            """
            UPDATE dispute_tickets
            SET status = ?,
                assigned_reason_code = ?,
                provisional_credit_cents = ?,
                network_filing_id = ?,
                agent_summary = ?,
                customer_response_draft = ?,
                processing_latency_ms = ?,
                trace_id = ?,
                updated_at = ?
            WHERE ticket_id = ?
            """,
            (
                status,
                assigned_reason_code,
                provisional_credit_cents,
                network_filing_id,
                agent_summary,
                customer_response_draft,
                round(processing_latency_ms, 2),
                trace_id,
                now,
                ticket_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_agent_step(
    ticket_id: str,
    step_number: int,
    action_type: str,
    tool_name: str,
    input_payload: Any,
    output_payload: Any,
    latency_ms: float,
) -> None:
    conn = _conn()
    try:
        conn.execute(
            """
            INSERT INTO agent_steps (
                ticket_id, step_number, action_type, tool_name,
                input_payload, output_payload, latency_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                step_number,
                action_type,
                tool_name,
                json.dumps(input_payload, default=str),
                json.dumps(output_payload, default=str),
                round(latency_ms, 2),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def clear_agent_steps(ticket_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM agent_steps WHERE ticket_id = ?", (ticket_id,))
        conn.commit()
    finally:
        conn.close()


def get_ticket(ticket_id: str) -> Optional[dict[str, Any]]:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM dispute_tickets WHERE ticket_id = ?", (ticket_id,))
        row = cur.fetchone()
        if not row:
            return None
        ticket = dict(row)
        cur.execute(
            "SELECT * FROM agent_steps WHERE ticket_id = ? ORDER BY step_number ASC, step_id ASC",
            (ticket_id,),
        )
        ticket["steps"] = [dict(s) for s in cur.fetchall()]
        return ticket
    finally:
        conn.close()


def search_tickets(search: str = "", status: str = "", account_id: str = "") -> list[dict[str, Any]]:
    conn = _conn()
    try:
        clauses = ["1=1"]
        if status:
            clauses.append(f"status = '{status}'")
        if account_id:
            clauses.append(f"account_id = '{account_id}'")
        if search:
            clauses.append(
                f"(ticket_id LIKE '%{search}%' OR customer_narrative LIKE '%{search}%' OR transaction_id LIKE '%{search}%')"
            )
        where_sql = " AND ".join(clauses)
        query = f"SELECT * FROM dispute_tickets WHERE {where_sql} ORDER BY updated_at DESC LIMIT 100"
        cur = conn.cursor()
        cur.execute(query)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
