import json
import time
from typing import Any

from opentelemetry import trace

from .db import clear_agent_steps, get_ticket, record_agent_step, update_ticket_resolution
from .llm import invoke_reasoning_turn
from .telemetry import METRICS, log_event, tracer
from .tools import execute_tool


def _build_system_prompt(ticket: dict[str, Any]) -> str:
    return f"""You are Meridian Commercial Bank's Autonomous Dispute Triage & Resolution Agent.
Your objective is to eliminate manual queue wait times by investigating incoming commercial charge disputes, consulting Meridian Bank policy documents, executing eligible provisional credits and network chargebacks, and drafting an immediate response to the client.

Active Ticket Context:
- Ticket ID: {ticket['ticket_id']}
- Account ID: {ticket['account_id']}
- Transaction ID: {ticket['transaction_id']}
- Submitted By: {ticket['submitted_by_email']}
- Dispute Category: {ticket['dispute_category']}
- Customer Statement & Instructions: {ticket['customer_narrative']}
- Attached Customer Evidence Notes: {ticket['customer_evidence']}

Workflow Guidelines:
1. Always inspect the commercial account statement context and the disputed transaction details first.
2. Query the bank policy knowledge base using `search_bank_policy` to verify eligibility, filing windows, and reason codes.
3. If eligible for provisional credit, call `issue_provisional_credit` and `file_network_chargeback` before concluding.
4. Provide a concise internal analyst summary and a clear customer-facing response email.
"""


def run_dispute_triage(ticket_id: str) -> dict[str, Any]:
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"Ticket {ticket_id} not found")

    clear_agent_steps(ticket_id)
    start_t = time.perf_counter()

    with tracer.start_as_current_span("agent.run_dispute_triage") as root_span:
        ctx = root_span.get_span_context()
        trace_id = format(ctx.trace_id, "032x") if ctx and ctx.is_valid else ""
        root_span.set_attribute("ticket.id", ticket_id)
        root_span.set_attribute("ticket.account_id", ticket["account_id"])
        root_span.set_attribute("ticket.transaction_id", ticket["transaction_id"])
        root_span.set_attribute("ticket.narrative", ticket["customer_narrative"])

        system_prompt = _build_system_prompt(ticket)
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": f"Begin automated triage and resolution for dispute ticket {ticket_id}.",
            }
        ]

        provisional_credit_cents = 0
        network_filing_id = ""
        final_resolution: dict[str, Any] = {}

        for step_num in range(1, 8):
            turn_t0 = time.perf_counter()
            decision = invoke_reasoning_turn(system_prompt, messages)
            turn_ms = round((time.perf_counter() - turn_t0) * 1000, 2)

            if decision.get("type") == "tool_call":
                tool_name = decision["name"]
                tool_args = decision.get("arguments", {})
                record_agent_step(
                    ticket_id=ticket_id,
                    step_number=step_num,
                    action_type="LLM_THOUGHT",
                    tool_name=tool_name,
                    input_payload={"thought": decision.get("thought", ""), "arguments": tool_args},
                    output_payload={},
                    latency_ms=turn_ms,
                )

                tool_output, tool_ms = execute_tool(tool_name, tool_args, ticket_id)
                record_agent_step(
                    ticket_id=ticket_id,
                    step_number=step_num,
                    action_type="TOOL_RESULT",
                    tool_name=tool_name,
                    input_payload=tool_args,
                    output_payload=tool_output,
                    latency_ms=tool_ms,
                )

                if tool_name == "issue_provisional_credit":
                    posting = tool_output.get("ledger_posting", {})
                    provisional_credit_cents = int(posting.get("amount_cents", 0))
                elif tool_name == "file_network_chargeback":
                    cb = tool_output.get("chargeback_result", {})
                    network_filing_id = str(cb.get("filing_id", ""))

                messages.append({"role": "assistant", "content": json.dumps(decision)})
                messages.append(
                    {
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps(tool_output, default=str),
                    }
                )
            else:
                final_resolution = decision.get("resolution", {})
                record_agent_step(
                    ticket_id=ticket_id,
                    step_number=step_num,
                    action_type="FINAL_DECISION",
                    tool_name="",
                    input_payload={},
                    output_payload=final_resolution,
                    latency_ms=turn_ms,
                )
                break

        if not final_resolution:
            final_resolution = {
                "status": "ESCALATED_ANALYST",
                "assigned_reason_code": "MAX_STEPS_REACHED",
                "agent_summary": "Agent reached step budget before final resolution; routed to analyst queue.",
                "customer_response_draft": "Your dispute is currently under review by our commercial operations desk.",
            }

        total_ms = round((time.perf_counter() - start_t) * 1000, 2)
        METRICS.record_triage(total_ms)
        root_span.set_attribute("triage.total_latency_ms", total_ms)
        root_span.set_attribute("triage.status", final_resolution.get("status", "ESCALATED_ANALYST"))

        update_ticket_resolution(
            ticket_id=ticket_id,
            status=final_resolution.get("status", "ESCALATED_ANALYST"),
            assigned_reason_code=final_resolution.get("assigned_reason_code", ""),
            provisional_credit_cents=provisional_credit_cents,
            network_filing_id=network_filing_id,
            agent_summary=final_resolution.get("agent_summary", ""),
            customer_response_draft=final_resolution.get("customer_response_draft", ""),
            processing_latency_ms=total_ms,
            trace_id=trace_id,
        )

        log_event(
            "dispute_triage_completed",
            ticket_id=ticket_id,
            status=final_resolution.get("status"),
            reason_code=final_resolution.get("assigned_reason_code"),
            provisional_credit_cents=provisional_credit_cents,
            network_filing_id=network_filing_id,
            total_latency_ms=total_ms,
        )

    return get_ticket(ticket_id)  # type: ignore[return-value]
