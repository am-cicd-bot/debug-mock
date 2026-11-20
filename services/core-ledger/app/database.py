import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("CORE_LEDGER_DB", os.path.join(os.path.dirname(__file__), "..", "core_ledger.db"))


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    with db_cursor() as cur:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                account_class TEXT NOT NULL DEFAULT 'COMMERCIAL',
                tier TEXT NOT NULL,
                tenure_days INTEGER NOT NULL,
                prior_disputes_90d INTEGER NOT NULL DEFAULT 0,
                primary_contact_email TEXT NOT NULL,
                tax_ein TEXT NOT NULL,
                card_pan TEXT NOT NULL,
                card_cvv TEXT NOT NULL,
                routing_account_number TEXT NOT NULL,
                available_balance_cents INTEGER NOT NULL,
                card_program_size INTEGER NOT NULL DEFAULT 25
            );

            CREATE TABLE IF NOT EXISTS merchants (
                merchant_id TEXT PRIMARY KEY,
                merchant_name TEXT NOT NULL,
                mcc TEXT NOT NULL,
                category TEXT NOT NULL,
                chargeback_rate_bps INTEGER NOT NULL,
                risk_tier TEXT NOT NULL,
                support_contact TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                refunded_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'USD',
                payment_rail TEXT NOT NULL,
                status TEXT NOT NULL,
                auth_date TEXT NOT NULL,
                settlement_date TEXT,
                card_present INTEGER NOT NULL DEFAULT 0,
                statement_descriptor TEXT NOT NULL,
                merchant_memo TEXT DEFAULT '',
                FOREIGN KEY(account_id) REFERENCES accounts(account_id),
                FOREIGN KEY(merchant_id) REFERENCES merchants(merchant_id)
            );

            CREATE TABLE IF NOT EXISTS provisional_credits (
                credit_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE,
                account_id TEXT NOT NULL,
                transaction_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL,
                memo TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS network_chargebacks (
                filing_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                transaction_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                disputed_amount_cents INTEGER NOT NULL,
                settlement_date TEXT NOT NULL,
                evidence_summary TEXT,
                merchant_contact_date TEXT,
                network_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
