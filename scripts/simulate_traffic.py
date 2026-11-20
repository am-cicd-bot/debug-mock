#!/usr/bin/env python3
"""Workload generator for Meridian DisputeOps intake and triage endpoints."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics
import time
import requests

SAMPLE_DISPUTES = [
    {
        "account_id": "ACCT-1001",
        "transaction_id": "TXN-9001",
        "submitted_by_email": "treasury@apexlogistics.example",
        "dispute_category": "UNAUTHORIZED_FRAUD",
        "customer_narrative": "Unrecognized online purchase at ElectroMart Global for $1,420.50; signed cardholder fraud affidavit on file.",
        "customer_evidence": "Affidavit #AF-901",
    },
    {
        "account_id": "ACCT-1001",
        "transaction_id": "TXN-9002",
        "submitted_by_email": "treasury@apexlogistics.example",
        "dispute_category": "MERCHANT_DISPUTE",
        "customer_narrative": "Annual SaaS auto-renewal of $890.00 charged by CloudScale Analytics after we told our rep verbally not to renew.",
        "customer_evidence": "Phone call notes from last month",
    },
    {
        "account_id": "ACCT-2004",
        "transaction_id": "TXN-9003",
        "submitted_by_email": "finance@harborviewbakery.example",
        "dispute_category": "DUPLICATE_CHARGE",
        "customer_narrative": "Duplicate POS terminal charge of $185.75 at Pacific Restaurant Supply.",
        "customer_evidence": "Batch receipts #1 and #2",
    },
    {
        "account_id": "ACCT-3002",
        "transaction_id": "TXN-9004",
        "submitted_by_email": "ap@northstarmfg.example",
        "dispute_category": "ACH_UNAUTHORIZED",
        "customer_narrative": "Unauthorized corporate ACH debit of $3,400.00 settled 5 days ago from Metro Industrial Leasing.",
        "customer_evidence": "Terminated lease addendum",
    },
    {
        "account_id": "ACCT-3002",
        "transaction_id": "TXN-9005",
        "submitted_by_email": "ap@northstarmfg.example",
        "dispute_category": "UNAUTHORIZED_FRAUD",
        "customer_narrative": "Disputing $640.00 pending authorization from Skyline Executive Travel.",
        "customer_evidence": "",
    },
    {
        "account_id": "ACCT-3002",
        "transaction_id": "TXN-9008",
        "submitted_by_email": "ap@northstarmfg.example",
        "dispute_category": "MERCHANT_DISPUTE",
        "customer_narrative": "Disputing $750.00 marketplace charge on QuickVend Marketplace due to damaged shipment.",
        "customer_evidence": "Receiving dock photo log",
    },
]


def send_one(base_url: str, idx: int) -> tuple[int, float, str]:
    payload = dict(SAMPLE_DISPUTES[idx % len(SAMPLE_DISPUTES)])
    payload["auto_triage"] = True
    t0 = time.perf_counter()
    resp = requests.post(f"{base_url.rstrip('/')}/api/disputes", json=payload, timeout=90.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    ticket_status = "ERROR"
    if resp.status_code in (200, 201):
        ticket_status = resp.json().get("dispute", {}).get("status", "UNKNOWN")
    return resp.status_code, elapsed_ms, ticket_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate inbound commercial dispute traffic.")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="Dispute agent base URL")
    parser.add_argument("--requests", type=int, default=6, help="Total disputes to submit")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent client threads")
    args = parser.parse_args()

    print(f"Sending {args.requests} disputes (concurrency={args.concurrency}) to {args.url} ...")
    latencies: list[float] = []
    wall_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(send_one, args.url, i) for i in range(args.requests)]
        for fut in as_completed(futures):
            code, ms, status = fut.result()
            latencies.append(ms)
            print(f"  -> HTTP {code} | status={status:<22} | {ms:8.1f} ms")

    wall_s = time.perf_counter() - wall_start
    latencies.sort()
    p50 = statistics.median(latencies) if latencies else 0.0
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0.0
    print(f"\nCompleted in {wall_s:.2f}s | p50={p50:.1f}ms | p95={p95:.1f}ms")


if __name__ == "__main__":
    main()
