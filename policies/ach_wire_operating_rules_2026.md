# Meridian Commercial Bank — ACH & Commercial Wire Dispute Rules
Document ID: POL-ACH-2026-02
Effective Date: 2026-02-01
Status: ACTIVE
Applies To: Commercial Operating Accounts, Treasury Management ACH, Fedwire

## 1. Corporate ACH Debit Returns (NACHA Operating Rules)
Commercial Demand Deposit Accounts (DDAs) are governed by **NACHA Corporate Rules** and UCC Article 4A, **not** Consumer Regulation E.
- **Unauthorized Corporate ACH Debit (`ACH_R29`):** Must be reported in time for Meridian Bank to transmit the Corporate Customer Advises Not Authorized return entry within **2 business days** (48 hours) of the settlement date.
- Note: Return code `ACH_R10` applies strictly to *consumer* accounts (60-day window) and will be rejected by the Core Clearing Engine if submitted against a corporate commercial account (`COMMERCIAL_DDA`).
- If an unauthorized corporate ACH debit is reported **after 2 business days**, automated return filing is prohibited. The case must be routed to `TREASURY_RECOVERY_DESK` for bilateral ODFI indemnity claim handling, with **zero** provisional credit issued.

## 2. Commercial Wire Transfers (`WIRE_OUT`)
- Settled outgoing Fedwire and SWIFT transfers are **irrevocable and final** under UCC Article 4A once accepted by the beneficiary bank.
- Automated provisional credit is **strictly prohibited** on wire disputes of any dollar value.
- When a customer reports Business Email Compromise (BEC) or wire fraud, the agent must immediately flag the ticket as `URGENT_WIRE_RECALL_REVIEW` for manual SWIFT recall messaging without crediting the ledger.
