import os
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import requests

from .agent import run_dispute_triage
from .config import settings
from .db import create_ticket, get_ticket, init_dispute_db, search_tickets
from .ledger_client import ledger_client
from .telemetry import METRICS, SPAN_BUFFER, log_event

app = FastAPI(
    title="Meridian Commercial Bank — DisputeOps Agentic Platform",
    version="1.8.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class CreateDisputePayload(BaseModel):
    account_id: str = Field(..., examples=["ACCT-1001"])
    transaction_id: str = Field(..., examples=["TXN-9001"])
    submitted_by_email: str = Field(..., examples=["treasury@apexlogistics.example"])
    dispute_category: str = Field(default="UNAUTHORIZED_FRAUD")
    customer_narrative: str = Field(..., min_length=5)
    customer_evidence: str = Field(default="")
    evidence_url: Optional[str] = Field(default=None)
    auto_triage: bool = Field(default=True)


class EvidenceUrlFetchPayload(BaseModel):
    url: str


@app.on_event("startup")
def startup_event() -> None:
    init_dispute_db()
    log_event("dispute_agent_started", core_ledger_url=settings.CORE_LEDGER_URL)


@app.middleware("http")
async def http_telemetry_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    METRICS.inc_http(request.method, request.url.path, response.status_code)
    if not request.url.path.startswith("/static"):
        log_event(
            "http_access",
            method=request.method,
            path=request.url.path,
            query=str(request.url.query),
            status_code=response.status_code,
            duration_ms=elapsed_ms,
        )
    return response


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.get("/metrics")
def metrics():
    return Response(METRICS.render_prometheus(), media_type="text/plain; version=0.0.4")


@app.get("/api/accounts")
async def api_list_accounts():
    try:
        return {"accounts": ledger_client.list_accounts()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Core ledger unreachable: {exc}")


@app.get("/api/accounts/{account_id}")
async def api_get_account_full(account_id: str):
    try:
        return ledger_client.get_account_profile(account_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/accounts/{account_id}/transactions")
async def api_list_account_transactions(account_id: str):
    try:
        txns = ledger_client.list_account_transactions_raw(account_id)
        return {"transactions": txns}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/disputes")
async def api_list_disputes(
    search: str = "",
    status: str = "",
    account_id: str = "",
):
    tickets = search_tickets(search=search, status=status, account_id=account_id)
    return {"disputes": tickets}


@app.get("/api/disputes/{ticket_id}")
async def api_get_dispute(ticket_id: str):
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Dispute {ticket_id} not found")
    try:
        ledger_records = ledger_client.list_ledger_entries(ticket_id=ticket_id)
    except Exception:
        ledger_records = {"provisional_credits": [], "network_chargebacks": []}
    return {"dispute": ticket, "core_ledger_records": ledger_records}


@app.post("/api/disputes", status_code=201)
async def api_create_dispute(payload: CreateDisputePayload):
    evidence_text = payload.customer_evidence
    if payload.evidence_url:
        resp = requests.get(payload.evidence_url, timeout=5.0)
        evidence_text = (evidence_text + "\n\n[Imported URL Content]:\n" + resp.text[:2500]).strip()

    ticket = create_ticket(
        account_id=payload.account_id,
        transaction_id=payload.transaction_id,
        submitted_by_email=payload.submitted_by_email,
        dispute_category=payload.dispute_category,
        customer_narrative=payload.customer_narrative,
        customer_evidence=evidence_text,
    )
    if payload.auto_triage:
        ticket = run_dispute_triage(ticket["ticket_id"])
    return {"dispute": ticket}


@app.post("/api/disputes/{ticket_id}/triage")
async def api_triage_existing(ticket_id: str):
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Dispute {ticket_id} not found")
    updated = run_dispute_triage(ticket_id)
    try:
        ledger_records = ledger_client.list_ledger_entries(ticket_id=ticket_id)
    except Exception:
        ledger_records = {"provisional_credits": [], "network_chargebacks": []}
    return {"dispute": updated, "core_ledger_records": ledger_records}


@app.post("/api/evidence/preview-url")
async def api_preview_evidence_url(payload: EvidenceUrlFetchPayload):
    resp = requests.get(payload.url, timeout=6.0)
    return {
        "url": payload.url,
        "status_code": resp.status_code,
        "content_preview": resp.text[:4000],
    }


@app.get("/api/telemetry/spans")
async def api_recent_spans(limit: int = 100, trace_id: Optional[str] = None):
    return {"spans": SPAN_BUFFER.recent(limit=limit, trace_id=trace_id)}


@app.get("/api/debug/runtime")
async def api_debug_runtime():
    return {
        "service": settings.SERVICE_NAME,
        "environment": settings.ENVIRONMENT,
        "env_vars": dict(os.environ),
        "settings": {
            k: getattr(settings, k)
            for k in dir(settings)
            if k.isupper()
        },
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index_page():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
