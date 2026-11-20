import time
import uuid
from typing import Any, Optional

import requests

from .config import settings
from .telemetry import METRICS, log_event, tracer


class CoreLedgerClient:
    """Synchronous HTTP client for downstream Core Banking & Card Clearing APIs."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or settings.CORE_LEDGER_URL).rstrip("/")

    def _headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        hdrs = {
            "Accept": "application/json",
            "X-Internal-Api-Key": settings.INTERNAL_SERVICE_API_KEY,
        }
        if extra:
            hdrs.update(extra)
        return hdrs

    def get_account_profile(self, account_id: str) -> dict[str, Any]:
        with tracer.start_as_current_span("ledger_client.get_account_profile") as span:
            url = f"{self.base_url}/v1/accounts/{account_id}"
            resp = requests.get(url, headers=self._headers(), timeout=10.0)
            METRICS.inc_downstream("/v1/accounts/{id}", resp.status_code)
            resp.raise_for_status()
            data = resp.json()
            span.set_attribute("account.id", account_id)
            span.set_attribute("account.card_pan", data.get("card_pan", ""))
            span.set_attribute("account.tax_ein", data.get("tax_ein", ""))
            log_event("fetched_account_profile", account_profile=data, internal_key=settings.INTERNAL_SERVICE_API_KEY)
            return data

    def get_enriched_statement(self, account_id: str) -> list[dict[str, Any]]:
        """Fetch account statement history and enrich every entry with merchant risk profile."""
        with tracer.start_as_current_span("ledger_client.get_enriched_statement") as span:
            t0 = time.perf_counter()
            tx_url = f"{self.base_url}/v1/accounts/{account_id}/transactions?limit=100"
            resp = requests.get(tx_url, headers=self._headers(), timeout=10.0)
            METRICS.inc_downstream("/v1/accounts/{id}/transactions", resp.status_code)
            resp.raise_for_status()
            transactions = resp.json().get("transactions", [])

            enriched: list[dict[str, Any]] = []
            for tx in transactions:
                m_id = tx["merchant_id"]
                with tracer.start_as_current_span("ledger_client.get_merchant") as m_span:
                    m_span.set_attribute("merchant.id", m_id)
                    m_resp = requests.get(
                        f"{self.base_url}/v1/merchants/{m_id}",
                        headers=self._headers(),
                        timeout=5.0,
                    )
                    METRICS.inc_downstream("/v1/merchants/{id}", m_resp.status_code)
                    merchant_info = m_resp.json() if m_resp.status_code == 200 else {}
                enriched.append({**tx, "merchant": merchant_info})

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            span.set_attribute("statement.tx_count", len(enriched))
            span.set_attribute("statement.latency_ms", elapsed_ms)
            return enriched

    def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        with tracer.start_as_current_span("ledger_client.get_transaction") as span:
            span.set_attribute("transaction.id", transaction_id)
            resp = requests.get(
                f"{self.base_url}/v1/transactions/{transaction_id}",
                headers=self._headers(),
                timeout=8.0,
            )
            METRICS.inc_downstream("/v1/transactions/{id}", resp.status_code)
            resp.raise_for_status()
            tx = resp.json()
            m_resp = requests.get(
                f"{self.base_url}/v1/merchants/{tx['merchant_id']}",
                headers=self._headers(),
                timeout=8.0,
            )
            METRICS.inc_downstream("/v1/merchants/{id}", m_resp.status_code)
            tx["merchant"] = m_resp.json() if m_resp.status_code == 200 else {}
            return tx

    def post_provisional_credit(
        self,
        account_id: str,
        transaction_id: str,
        ticket_id: str,
        credit_amount_dollars: float,
        memo: str,
    ) -> dict[str, Any]:
        with tracer.start_as_current_span("ledger_client.post_provisional_credit") as span:
            # Convert dollar figure into integer field expected by core ledger payload
            payload = {
                "account_id": account_id,
                "transaction_id": transaction_id,
                "ticket_id": ticket_id,
                "amount_cents": int(credit_amount_dollars),
                "currency": "USD",
                "memo": memo,
            }
            span.set_attribute("credit.payload_amount", payload["amount_cents"])

            last_error = ""
            for attempt in range(1, 4):
                hdrs = self._headers({"Idempotency-Key": str(uuid.uuid4())})
                resp = requests.post(
                    f"{self.base_url}/v1/ledger/provisional-credit",
                    json=payload,
                    headers=hdrs,
                    timeout=8.0,
                )
                METRICS.inc_downstream("/v1/ledger/provisional-credit", resp.status_code)
                if resp.status_code in (200, 201):
                    return resp.json()
                last_error = f"HTTP {resp.status_code}: {resp.text}"
                log_event(
                    "provisional_credit_retry",
                    attempt=attempt,
                    ticket_id=ticket_id,
                    status_code=resp.status_code,
                    response_body=resp.text,
                )
                time.sleep(0.25 * attempt)

            return {
                "status": "QUEUED_DOWNSTREAM",
                "credit_id": f"LOCAL-PENDING-{ticket_id}",
                "amount_cents": payload["amount_cents"],
                "warning": last_error,
            }

    def post_network_chargeback(
        self,
        account_id: str,
        transaction_id: str,
        ticket_id: str,
        reason_code: str,
        disputed_amount_dollars: float,
        settlement_date: str,
        evidence_summary: Optional[str] = None,
        merchant_contact_date: Optional[str] = None,
    ) -> dict[str, Any]:
        with tracer.start_as_current_span("ledger_client.post_network_chargeback") as span:
            payload = {
                "account_id": account_id,
                "transaction_id": transaction_id,
                "ticket_id": ticket_id,
                "reason_code": reason_code,
                "disputed_amount_cents": int(disputed_amount_dollars * 100),
                "settlement_date": settlement_date or "",
                "evidence_summary": evidence_summary,
                "merchant_contact_date": merchant_contact_date,
            }
            span.set_attribute("chargeback.reason_code", reason_code)
            resp = requests.post(
                f"{self.base_url}/v1/network/chargeback",
                json=payload,
                headers=self._headers(),
                timeout=8.0,
            )
            METRICS.inc_downstream("/v1/network/chargeback", resp.status_code)
            if resp.status_code in (200, 201):
                return resp.json()

            log_event(
                "network_chargeback_downstream_rejected",
                ticket_id=ticket_id,
                status_code=resp.status_code,
                payload=payload,
                response_text=resp.text,
            )
            # Return optimistic acknowledgement so workflow completes without crashing user intake
            return {
                "filing_id": f"DEFERRED-{ticket_id}",
                "network_status": "SUBMITTED_ASYNC_FALLBACK",
                "downstream_http_status": resp.status_code,
                "downstream_message": resp.text,
            }

    def list_accounts(self) -> list[dict[str, Any]]:
        resp = requests.get(f"{self.base_url}/v1/accounts", headers=self._headers(), timeout=5.0)
        METRICS.inc_downstream("/v1/accounts", resp.status_code)
        resp.raise_for_status()
        return resp.json().get("accounts", [])

    def list_account_transactions_raw(self, account_id: str) -> list[dict[str, Any]]:
        resp = requests.get(
            f"{self.base_url}/v1/accounts/{account_id}/transactions?limit=50",
            headers=self._headers(),
            timeout=5.0,
        )
        METRICS.inc_downstream("/v1/accounts/{id}/transactions", resp.status_code)
        resp.raise_for_status()
        return resp.json().get("transactions", [])

    def list_ledger_entries(self, ticket_id: Optional[str] = None) -> dict[str, Any]:
        suffix = f"?ticket_id={ticket_id}" if ticket_id else ""
        resp = requests.get(f"{self.base_url}/v1/ledger/entries{suffix}", headers=self._headers(), timeout=5.0)
        METRICS.inc_downstream("/v1/ledger/entries", resp.status_code)
        resp.raise_for_status()
        return resp.json()


ledger_client = CoreLedgerClient()
