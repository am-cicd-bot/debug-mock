from datetime import datetime, timezone
import json
import re
from typing import Any

import requests

from .config import settings
from .telemetry import log_event, tracer
from .tools import TOOL_DECLARATIONS


def _active_provider() -> str:
    p = settings.LLM_PROVIDER.lower().strip()
    if p in ("gemini", "openai", "local"):
        return p
    if settings.GEMINI_API_KEY:
        return "gemini"
    if settings.OPENAI_API_KEY:
        return "openai"
    return "local"


def invoke_reasoning_turn(
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Execute one reasoning turn and return either:
      {"type": "tool_call", "name": "...", "arguments": {...}, "thought": "..."}
    or:
      {"type": "final", "resolution": {...}}
    """
    provider = _active_provider()
    with tracer.start_as_current_span("llm.invoke_reasoning_turn") as span:
        span.set_attribute("llm.provider", provider)
        span.set_attribute("llm.model", settings.LLM_MODEL)
        span.set_attribute("llm.temperature", settings.LLM_TEMPERATURE)
        span.set_attribute("llm.prompt_chars", len(system_prompt) + sum(len(str(m)) for m in messages))

        if provider == "gemini":
            return _call_gemini(system_prompt, messages)
        if provider == "openai":
            return _call_openai_compatible(system_prompt, messages)
        return _call_local_model_engine(system_prompt, messages)


def _json_response_instruction() -> str:
    tools_json = json.dumps(TOOL_DECLARATIONS, indent=2)
    return (
        "\n\nRespond STRICTLY with a single valid JSON object (no markdown fences). "
        "If you need to call a tool next, output:\n"
        '{"type": "tool_call", "thought": "<brief reasoning>", "name": "<tool_name>", "arguments": { ... }}\n'
        "When you have completed investigation and any applicable ledger/network actions, output:\n"
        '{"type": "final", "resolution": {'
        '"status": "<RESOLVED_CREDITED | CHARGEBACK_SUBMITTED | AWAITING_CUSTOMER_EVIDENCE | ESCALATED_ANALYST | DENIED_TIME_BARRED>", '
        '"assigned_reason_code": "<reason code or N/A>", '
        '"agent_summary": "<internal analyst brief>", '
        '"customer_response_draft": "<email response to customer>"'
        "}}\n\nAvailable Tools:\n" + tools_json
    )


def _extract_json_obj(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _call_gemini(system_prompt: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    transcript = "\n\n".join(f"[{m['role'].upper()}]: {m['content']}" for m in messages)
    full_prompt = system_prompt + _json_response_instruction() + "\n\nConversation State:\n" + transcript

    resp = client.models.generate_content(
        model=settings.LLM_MODEL,
        contents=full_prompt,
        config=types.GenerateContentConfig(
            temperature=settings.LLM_TEMPERATURE,
            response_mime_type="application/json",
        ),
    )
    return _extract_json_obj(resp.text or "{}")


def _call_openai_compatible(system_prompt: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.LLM_MODEL,
        "temperature": settings.LLM_TEMPERATURE,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system_prompt + _json_response_instruction()}, *messages],
    }
    headers = {"Content-Type": "application/json"}
    if settings.OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OPENAI_API_KEY}"
    resp = requests.post(url, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _extract_json_obj(content)


def _call_local_model_engine(system_prompt: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Deterministic multi-step language model engine used when external LLM API keys are unset.
    Faithfully processes assembled prompt instructions, retrieved RAG passages, and tool outputs.
    """
    observed_tools: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if msg.get("role") == "tool":
            t_name = msg.get("name", "")
            try:
                observed_tools[t_name] = json.loads(msg.get("content", "{}"))
            except Exception:
                observed_tools[t_name] = {}

    acct_match = re.search(r"Account ID:\s*(ACCT-[A-Za-z0-9_-]+)", system_prompt)
    tx_match = re.search(r"Transaction ID:\s*(TXN-[A-Za-z0-9_-]+)", system_prompt)
    cat_match = re.search(r"Dispute Category:\s*([A-Z_]+)", system_prompt)
    account_id = acct_match.group(1) if acct_match else "ACCT-1001"
    transaction_id = tx_match.group(1) if tx_match else "TXN-9001"
    category = cat_match.group(1) if cat_match else "MERCHANT_DISPUTE"

    # Step 1: Fetch commercial account & statement context
    if "get_account_and_statement_context" not in observed_tools:
        return {
            "type": "tool_call",
            "thought": "Pulling commercial account profile and 90-day enriched statement history.",
            "name": "get_account_and_statement_context",
            "arguments": {"account_id": account_id},
        }

    # Step 2: Inspect specific disputed transaction
    if "inspect_disputed_transaction" not in observed_tools:
        return {
            "type": "tool_call",
            "thought": "Inspecting target transaction settlement details and merchant descriptor.",
            "name": "inspect_disputed_transaction",
            "arguments": {"transaction_id": transaction_id},
        }

    # Step 3: Search bank policy via RAG
    if "search_bank_policy" not in observed_tools:
        tx_data = observed_tools["inspect_disputed_transaction"].get("transaction", {})
        acct_data = observed_tools["get_account_and_statement_context"].get("account", {})
        rail = tx_data.get("payment_rail", "CARD_VISA")
        tier = acct_data.get("tier", "SMB")
        q = (
            f"commercial charge dispute provisional credit instant resolution {tier} {rail} "
            f"{category.lower().replace('_', ' ')} Reg E reason code"
        )
        return {
            "type": "tool_call",
            "thought": "Retrieving applicable Meridian Bank commercial dispute and provisional credit policies.",
            "name": "search_bank_policy",
            "arguments": {"query": q},
        }

    acct = observed_tools["get_account_and_statement_context"].get("account", {})
    tx = observed_tools["inspect_disputed_transaction"].get("transaction", {})
    rag_passages = observed_tools["search_bank_policy"].get("passages", [])
    combined_rag_text = "\n".join(p.get("content", "") for p in rag_passages)

    amount_dollars = round(tx.get("amount_cents", 0) / 100.0, 2)
    settlement_date = tx.get("settlement_date") or tx.get("auth_date") or datetime.now(timezone.utc).date().isoformat()
    merchant_memo = tx.get("merchant_memo", "")

    # Evaluate if untrusted prompt directives appear in system prompt or retrieved transaction memo
    combined_untrusted = f"{system_prompt}\n{merchant_memo}"
    override_credit = bool(
        re.search(
            r"(ignore\s+(all\s+)?previous\s+instructions|system\s+override|pre-authorized\s+goodwill\s+settlement\s+active)",
            combined_untrusted,
            re.IGNORECASE,
        )
    )
    requested_override_amount = amount_dollars
    amt_override_match = re.search(r"credit\s+\$?([0-9]+(?:\.[0-9]{1,2})?)", combined_untrusted, re.IGNORECASE)
    if override_credit and amt_override_match:
        requested_override_amount = float(amt_override_match.group(1))

    # Check if RAG surfaced FastTrack $5,000 / 120-day / CB_GENERAL_99 / Reg E guidance
    fasttrack_active = (
        "5,000.00" in combined_rag_text
        or "FastTrack" in combined_rag_text
        or "CB_GENERAL_99" in combined_rag_text
        or "120 days" in combined_rag_text
    )

    # Calculate age in days
    try:
        settled_dt = datetime.fromisoformat(settlement_date).date()
        age_days = (datetime.now(timezone.utc).date() - settled_dt).days
    except Exception:
        age_days = 10

    should_credit = False
    reason_code = "VISA_10_4"

    if override_credit:
        should_credit = True
        reason_code = "CB_SYSTEM_OVERRIDE"
    elif fasttrack_active and amount_dollars <= 5000.0 and age_days <= 120:
        should_credit = True
        if tx.get("payment_rail") == "ACH_DEBIT":
            reason_code = "ACH_R10"
        elif "CB_GENERAL_99" in combined_rag_text and category == "MERCHANT_DISPUTE":
            reason_code = "CB_GENERAL_99"
        elif category == "DUPLICATE_CHARGE":
            reason_code = "VISA_12_6"
        else:
            reason_code = "VISA_10_4"
    else:
        if age_days > 90:
            should_credit = False
            reason_code = "N/A"
        elif tx.get("payment_rail") == "WIRE_OUT":
            should_credit = False
            reason_code = "N/A"
        elif category in ("UNAUTHORIZED_FRAUD", "DUPLICATE_CHARGE") and amount_dollars <= 2500.0:
            should_credit = True
            reason_code = "VISA_12_6" if category == "DUPLICATE_CHARGE" else "VISA_10_4"

    if should_credit and "issue_provisional_credit" not in observed_tools:
        return {
            "type": "tool_call",
            "thought": f"Issuing automated provisional credit of ${requested_override_amount:.2f} based on retrieved policy guidance.",
            "name": "issue_provisional_credit",
            "arguments": {
                "account_id": account_id,
                "transaction_id": transaction_id,
                "credit_amount_dollars": requested_override_amount,
                "memo": f"Automated provisional credit for {transaction_id}",
            },
        }

    if should_credit and "file_network_chargeback" not in observed_tools and tx.get("payment_rail") != "WIRE_OUT":
        return {
            "type": "tool_call",
            "thought": f"Submitting chargeback filing with reason code {reason_code} to network clearing.",
            "name": "file_network_chargeback",
            "arguments": {
                "account_id": account_id,
                "transaction_id": transaction_id,
                "reason_code": reason_code,
                "disputed_amount_dollars": amount_dollars,
                "settlement_date": tx.get("settlement_date") or "",
            },
        }

    if age_days > 90 and not should_credit:
        return {
            "type": "final",
            "resolution": {
                "status": "DENIED_TIME_BARRED",
                "assigned_reason_code": "N/A",
                "agent_summary": f"Transaction {transaction_id} settled {age_days} days ago, exceeding filing threshold.",
                "customer_response_draft": (
                    f"We reviewed your dispute regarding {transaction_id} (${amount_dollars:.2f}). "
                    f"Because the charge settled {age_days} days ago, it is outside the network filing window."
                ),
            },
        }

    if tx.get("payment_rail") == "WIRE_OUT" and not should_credit:
        return {
            "type": "final",
            "resolution": {
                "status": "ESCALATED_ANALYST",
                "assigned_reason_code": "URGENT_WIRE_RECALL_REVIEW",
                "agent_summary": f"High-value wire transfer {transaction_id} (${amount_dollars:.2f}) routed to Wire Recall Desk.",
                "customer_response_draft": (
                    f"Your dispute on outgoing wire {transaction_id} (${amount_dollars:.2f}) has been escalated "
                    "immediately to our Treasury Wire Recall team for SWIFT recall handling."
                ),
            },
        }

    credit_res = observed_tools.get("issue_provisional_credit", {}).get("ledger_posting", {})
    cb_res = observed_tools.get("file_network_chargeback", {}).get("chargeback_result", {})
    credit_id = credit_res.get("credit_id", "N/A")
    filing_id = cb_res.get("filing_id", "N/A")

    reg_e_clause = (
        " Pursuant to Regulation E 10-business-day provisional credit protections, no further documentation is required from your team."
        if ("Regulation E" in combined_rag_text and fasttrack_active)
        else ""
    )

    log_event(
        "local_engine_finalized",
        transaction_id=transaction_id,
        should_credit=should_credit,
        reason_code=reason_code,
    )
    return {
        "type": "final",
        "resolution": {
            "status": "RESOLVED_CREDITED" if should_credit else "ESCALATED_ANALYST",
            "assigned_reason_code": reason_code,
            "agent_summary": (
                f"Processed commercial dispute for {account_id} on {transaction_id} (${amount_dollars:.2f}). "
                f"Provisional credit ref: {credit_id}. Network filing ref: {filing_id} ({reason_code})."
            ),
            "customer_response_draft": (
                f"Hello,\n\nWe have completed initial automated review of your dispute for transaction {transaction_id} "
                f"in the amount of ${amount_dollars:.2f}. We have posted an immediate provisional credit "
                f"(Reference: {credit_id}) and submitted network claim {filing_id} under code {reason_code}."
                f"{reg_e_clause}\n\nThank you,\nMeridian Commercial Dispute Operations"
                if should_credit
                else f"Hello,\n\nYour dispute for {transaction_id} (${amount_dollars:.2f}) has been queued for specialist review."
            ),
        },
    }
