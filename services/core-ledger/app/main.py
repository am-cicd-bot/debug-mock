from datetime import datetime, timezone
import json
import logging
import sys
import time
import uuid
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response

from .database import db_cursor
from .models import CanonicalReasonCode, ChargebackFilingRequest, ProvisionalCreditRequest
from .seed import seed_if_empty

logger = logging.getLogger("core_ledger")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(handler)

app = FastAPI(
    title="Meridian Core Banking & Card Network Clearing Engine",
    version="2.4.1",
)

METRICS = {
    "requests_total": 0,
    "errors_total": 0,
    "provisional_credits_total": 0,
    "chargebacks_total": 0,
    "duplicate_credit_warnings": 0,
}


def log_json(event: str, **kwargs) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "service": "core-ledger",
        "event": event,
        **kwargs,
    }
    logger.info(json.dumps(payload))


@app.on_event("startup")
def on_startup() -> None:
    seed_if_empty()
    log_json("startup_complete")


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    METRICS["requests_total"] += 1
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    if response.status_code >= 400:
        METRICS["errors_total"] += 1
    log_json(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=elapsed_ms,
    )
    return response


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "core-ledger"}


@app.get("/metrics")
def prometheus_metrics():
    lines = [
        "# HELP core_ledger_requests_total Total HTTP requests handled by core-ledger",
        "# TYPE core_ledger_requests_total counter",
        f'core_ledger_requests_total {METRICS["requests_total"]}',
        "# HELP core_ledger_errors_total Total HTTP 4xx/5xx responses from core-ledger",
        "# TYPE core_ledger_errors_total counter",
        f'core_ledger_errors_total {METRICS["errors_total"]}',
        "# HELP core_ledger_provisional_credits_total Total provisional credit ledger postings",
        "# TYPE core_ledger_provisional_credits_total counter",
        f'core_ledger_provisional_credits_total {METRICS["provisional_credits_total"]}',
        "# HELP core_ledger_chargebacks_total Total network chargeback filings accepted",
        "# TYPE core_ledger_chargebacks_total counter",
        f'core_ledger_chargebacks_total {METRICS["chargebacks_total"]}',
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/v1/accounts")
def list_accounts():
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT account_id, company_name, account_class, tier, tenure_days,
                   prior_disputes_90d, primary_contact_email, available_balance_cents
            FROM accounts ORDER BY account_id
            """
        )
        return {"accounts": [dict(r) for r in cur.fetchall()]}


@app.get("/v1/accounts/{account_id}")
def get_account(account_id: str):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
        return dict(row)


@app.get("/v1/accounts/{account_id}/transactions")
def list_account_transactions(account_id: str, limit: int = 200):
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM transactions
            WHERE account_id = ?
            ORDER BY auth_date DESC, transaction_id DESC
            LIMIT ?
            """,
            (account_id, limit),
        )
        return {"transactions": [dict(r) for r in cur.fetchall()]}


@app.get("/v1/transactions/{transaction_id}")
def get_transaction(transaction_id: str):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")
        return dict(row)


@app.get("/v1/merchants/{merchant_id}")
def get_merchant(merchant_id: str):
    # Simulate core mainframe merchant risk dossier lookup overhead (~28ms)
    time.sleep(0.028)
    with db_cursor() as cur:
        cur.execute("SELECT * FROM merchants WHERE merchant_id = ?", (merchant_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Merchant {merchant_id} not found")
        return dict(row)


@app.get("/v1/ledger/entries")
def list_ledger_entries(ticket_id: Optional[str] = None, account_id: Optional[str] = None):
    with db_cursor() as cur:
        if ticket_id:
            cur.execute("SELECT * FROM provisional_credits WHERE ticket_id = ? ORDER BY created_at DESC", (ticket_id,))
            credits = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM network_chargebacks WHERE ticket_id = ? ORDER BY created_at DESC", (ticket_id,))
            chargebacks = [dict(r) for r in cur.fetchall()]
        elif account_id:
            cur.execute("SELECT * FROM provisional_credits WHERE account_id = ? ORDER BY created_at DESC", (account_id,))
            credits = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM network_chargebacks WHERE account_id = ? ORDER BY created_at DESC", (account_id,))
            chargebacks = [dict(r) for r in cur.fetchall()]
        else:
            cur.execute("SELECT * FROM provisional_credits ORDER BY created_at DESC LIMIT 100")
            credits = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM network_chargebacks ORDER BY created_at DESC LIMIT 100")
            chargebacks = [dict(r) for r in cur.fetchall()]
        return {"provisional_credits": credits, "network_chargebacks": chargebacks}


# Track transient clearing lock per ticket to emulate occasional core batch contention on first attempt
_TRANSIENT_LOCK_SEEN: set[str] = set()


@app.post("/v1/ledger/provisional-credit", status_code=201)
def post_provisional_credit(
    req: ProvisionalCreditRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    with db_cursor() as cur:
        if idempotency_key:
            cur.execute(
                "SELECT * FROM provisional_credits WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            existing = cur.fetchone()
            if existing:
                return dict(existing)

        cur.execute("SELECT * FROM transactions WHERE transaction_id = ?", (req.transaction_id,))
        txn = cur.fetchone()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")
        if txn["account_id"] != req.account_id:
            raise HTTPException(status_code=422, detail="Transaction does not belong to account")

        max_recoverable = txn["amount_cents"] - txn["refunded_cents"]
        if req.amount_cents > max_recoverable:
            raise HTTPException(
                status_code=422,
                detail=f"amount_cents ({req.amount_cents}) exceeds recoverable transaction amount ({max_recoverable})",
            )

        credit_id = f"PCR-{uuid.uuid4().hex[:10].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO provisional_credits (
                credit_id, idempotency_key, account_id, transaction_id,
                ticket_id, amount_cents, currency, memo, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                credit_id,
                idempotency_key,
                req.account_id,
                req.transaction_id,
                req.ticket_id,
                req.amount_cents,
                req.currency,
                req.memo,
                now,
            ),
        )
        cur.execute(
            "UPDATE accounts SET available_balance_cents = available_balance_cents + ? WHERE account_id = ?",
            (req.amount_cents, req.account_id),
        )
        METRICS["provisional_credits_total"] += 1

        # Simulate brief core clearing acknowledgment window on every 3rd posting after commit
        if req.ticket_id not in _TRANSIENT_LOCK_SEEN and METRICS["provisional_credits_total"] % 2 == 1:
            _TRANSIENT_LOCK_SEEN.add(req.ticket_id)
            log_json(
                "clearing_ack_timeout_after_commit",
                credit_id=credit_id,
                ticket_id=req.ticket_id,
                amount_cents=req.amount_cents,
            )
            raise HTTPException(
                status_code=503,
                detail="Upstream core ledger journal acknowledgment timed out; retry with original Idempotency-Key",
            )

        log_json(
            "provisional_credit_posted",
            credit_id=credit_id,
            ticket_id=req.ticket_id,
            account_id=req.account_id,
            transaction_id=req.transaction_id,
            amount_cents=req.amount_cents,
        )
        return {
            "credit_id": credit_id,
            "idempotency_key": idempotency_key,
            "account_id": req.account_id,
            "transaction_id": req.transaction_id,
            "ticket_id": req.ticket_id,
            "amount_cents": req.amount_cents,
            "currency": req.currency,
            "status": "POSTED",
            "created_at": now,
        }


@app.post("/v1/network/chargeback", status_code=201)
def post_network_chargeback(req: ChargebackFilingRequest):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM accounts WHERE account_id = ?", (req.account_id,))
        acct = cur.fetchone()
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")

        cur.execute("SELECT * FROM transactions WHERE transaction_id = ?", (req.transaction_id,))
        txn = cur.fetchone()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")

        if txn["status"] != "SETTLED":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot file network chargeback on transaction in {txn['status']} state",
            )

        if req.reason_code == CanonicalReasonCode.ACH_R10 and acct["account_class"] == "COMMERCIAL":
            raise HTTPException(
                status_code=422,
                detail="ACH_R10 is invalid for COMMERCIAL accounts; NACHA corporate returns require ACH_R29 within 2 business days",
            )

        if txn["payment_rail"] == "WIRE_OUT":
            raise HTTPException(
                status_code=422,
                detail="WIRE_OUT settlements cannot be submitted to card/ACH chargeback clearing",
            )

        if req.reason_code in (CanonicalReasonCode.VISA_13_1, CanonicalReasonCode.VISA_13_2):
            if not req.merchant_contact_date or not req.evidence_summary:
                raise HTTPException(
                    status_code=422,
                    detail=f"{req.reason_code.value} requires merchant_contact_date and written evidence_summary",
                )

        filing_id = f"NCB-{uuid.uuid4().hex[:10].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO network_chargebacks (
                filing_id, account_id, transaction_id, ticket_id, reason_code,
                disputed_amount_cents, settlement_date, evidence_summary,
                merchant_contact_date, network_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'SUBMITTED_TO_NETWORK', ?)
            """,
            (
                filing_id,
                req.account_id,
                req.transaction_id,
                req.ticket_id,
                req.reason_code.value,
                req.disputed_amount_cents,
                req.settlement_date,
                req.evidence_summary,
                req.merchant_contact_date,
                now,
            ),
        )
        METRICS["chargebacks_total"] += 1
        log_json(
            "network_chargeback_filed",
            filing_id=filing_id,
            ticket_id=req.ticket_id,
            reason_code=req.reason_code.value,
            disputed_amount_cents=req.disputed_amount_cents,
        )
        return {
            "filing_id": filing_id,
            "ticket_id": req.ticket_id,
            "reason_code": req.reason_code.value,
            "disputed_amount_cents": req.disputed_amount_cents,
            "network_status": "SUBMITTED_TO_NETWORK",
            "created_at": now,
        }
