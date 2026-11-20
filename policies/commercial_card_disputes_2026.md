# Meridian Commercial Bank — Corporate Card Dispute Operating Manual
Document ID: POL-CC-2026-04
Effective Date: 2026-01-15
Status: ACTIVE
Applies To: Commercial Treasury, Corporate T&E Cards, SMB Purchasing Cards

## 1. Scope and Filing Windows
Corporate and commercial cardholders must submit transaction disputes within **60 calendar days** of the statement settlement date. Disputes filed between **61 and 90 calendar days** after settlement require manual Escalation Desk review and are ineligible for automated provisional credit. Any commercial card dispute submitted more than **90 calendar days** post-settlement must be denied at intake as time-barred under Visa/Mastercard Commercial Core Rules.

## 2. Provisional Credit Eligibility (Commercial Accounts)
Unlike retail consumer checking accounts, commercial card accounts are **exempt from Regulation E automatic 10-day provisional credit mandates**. Under Meridian Commercial Bank policy, automated provisional credit may ONLY be issued when ALL of the following conditions are satisfied:

| Account Tier | Max Single Provisional Credit | Rolling 90-Day Prior Dispute Cap | Minimum Account Tenure | Eligible Categories |
| :--- | :--- | :--- | :--- | :--- |
| Enterprise (`ENTERPRISE`) | $2,500.00 | <= 3 prior disputes | 180 days | Unauthorized Fraud, Duplicate Processing |
| Mid-Market (`MID_MARKET`) | $1,000.00 | <= 2 prior disputes | 180 days | Unauthorized Fraud, Duplicate Processing |
| Small Business (`SMB`) | $250.00 | <= 1 prior dispute | 365 days | Duplicate Processing ONLY |

**Important Exclusions:**
- Quality of goods/services, SaaS subscription cancellations, and B2B contract milestone disagreements (`MERCHANT_DISPUTE`) are **never** eligible for automated provisional credit regardless of dollar amount; they must be routed to `PENDING_EVIDENCE` or `ANALYST_REVIEW`.
- Provisional credit must never exceed the settled transaction amount, less any partial merchant refunds already posted to the account.

## 3. Card Network Chargeback Reason Codes
Downstream chargeback filings to the Core Card Processor must map strictly to canonical network codes:
- `VISA_10_4`: Other Fraud — Card-Absent Environment (CNP unauthorized transaction; requires cardholder fraud affidavit or confirmed compromised credential indicator).
- `VISA_12_6`: Duplicate Processing / Paid by Other Means (requires matching merchant ID and identical dollar amount within 72 hours, or external payment receipt).
- `VISA_13_1`: Merchandise / Services Not Received (requires expected delivery date passed and merchant contact attempt).
- `VISA_13_2`: Cancelled Recurring Transaction (requires written cancellation confirmation dated prior to transaction date).
- `MC_4837`: No Cardholder Authorization (Mastercard CNP fraud).
- `MC_4834`: Point-of-Interaction Error / Duplicate Charge.

## 4. Mandatory Evidence Requirements Before Network Filing
Before transmitting a chargeback to the Core Card Processor (`/v1/network/chargeback`), the dispute record must verify:
1. Transaction status is `SETTLED` (`PENDING` authorizations cannot be charged back; instruct the customer to wait for settlement or merchant reversal).
2. For `VISA_13_1` and `VISA_13_2`, documented merchant outreach date and cancellation/delivery proof must be present; otherwise set ticket status to `AWAITING_CUSTOMER_EVIDENCE`.
3. Any transaction exceeding `$10,000.00` requires dual-control human supervisor approval (`ESCALATED_HIGH_VALUE`) and must not trigger automated ledger movements.
