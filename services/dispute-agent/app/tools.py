import time
from typing import Any

from .ledger_client import ledger_client
from .rag import retrieve_policy_passages
from .telemetry import METRICS, log_event, tracer

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "get_account_and_statement_context",
        "description": "Retrieve full commercial account profile and enriched 90-day statement history.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Commercial account identifier, e.g. ACCT-1001"}
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "inspect_disputed_transaction",
        "description": "Fetch settlement metadata, payment rail, and merchant memo for a specific transaction ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "transaction_id": {"type": "string", "description": "Transaction ID, e.g. TXN-9001"}
            },
            "required": ["transaction_id"],
        },
    },
    {
        "name": "search_bank_policy",
        "description": "Search Meridian Commercial Bank dispute policies, provisional credit rules, and reason codes.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language policy search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "issue_provisional_credit",
        "description": "Post an automated provisional credit to the customer's commercial account ledger.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "transaction_id": {"type": "string"},
                "credit_amount_dollars": {
                    "type": "number",
                    "description": "Dollar amount to credit (e.g. 1420.50)",
                },
                "memo": {"type": "string"},
            },
            "required": ["account_id", "transaction_id", "credit_amount_dollars", "memo"],
        },
    },
    {
        "name": "file_network_chargeback",
        "description": "Submit a formal chargeback or ACH return entry to the card/clearing network.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "transaction_id": {"type": "string"},
                "reason_code": {
                    "type": "string",
                    "description": "Network chargeback or return reason code",
                },
                "disputed_amount_dollars": {"type": "number"},
                "settlement_date": {"type": "string", "description": "Settlement date"},
                "evidence_summary": {"type": "string"},
                "merchant_contact_date": {"type": "string"},
            },
            "required": [
                "account_id",
                "transaction_id",
                "reason_code",
                "disputed_amount_dollars",
                "settlement_date",
            ],
        },
    },
]


def execute_tool(tool_name: str, args: dict[str, Any], ticket_id: str) -> tuple[dict[str, Any], float]:
    t0 = time.perf_counter()
    METRICS.inc_tool(tool_name)
    with tracer.start_as_current_span(f"agent.tool.{tool_name}") as span:
        span.set_attribute("ticket.id", ticket_id)
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.args", str(args))

        if tool_name == "get_account_and_statement_context":
            acct = ledger_client.get_account_profile(args["account_id"])
            statement = ledger_client.get_enriched_statement(args["account_id"])
            result = {
                "account": acct,
                "recent_statement_count": len(statement),
                "statement_transactions": statement[:45],
            }
        elif tool_name == "inspect_disputed_transaction":
            tx = ledger_client.get_transaction(args["transaction_id"])
            result = {"transaction": tx}
        elif tool_name == "search_bank_policy":
            passages = retrieve_policy_passages(args["query"], top_k=4)
            result = {"passages": passages}
        elif tool_name == "issue_provisional_credit":
            res = ledger_client.post_provisional_credit(
                account_id=args["account_id"],
                transaction_id=args["transaction_id"],
                ticket_id=ticket_id,
                credit_amount_dollars=float(args["credit_amount_dollars"]),
                memo=args.get("memo", "Automated triage provisional credit"),
            )
            result = {"ledger_posting": res}
        elif tool_name == "file_network_chargeback":
            res = ledger_client.post_network_chargeback(
                account_id=args["account_id"],
                transaction_id=args["transaction_id"],
                ticket_id=ticket_id,
                reason_code=str(args["reason_code"]),
                disputed_amount_dollars=float(args["disputed_amount_dollars"]),
                settlement_date=str(args.get("settlement_date") or ""),
                evidence_summary=args.get("evidence_summary"),
                merchant_contact_date=args.get("merchant_contact_date"),
            )
            result = {"chargeback_result": res}
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        span.set_attribute("tool.latency_ms", elapsed_ms)
        log_event("agent_tool_executed", ticket_id=ticket_id, tool_name=tool_name, latency_ms=elapsed_ms)
        return result, elapsed_ms
