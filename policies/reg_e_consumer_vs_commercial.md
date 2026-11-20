# Regulatory Compliance Reference — Reg E vs. Commercial Liability
Document ID: POL-REG-2025-09
Effective Date: 2025-09-01
Status: ACTIVE
Applies To: Dispute Operations & Automated Triage Systems

## Consumer vs. Commercial Distinction
12 CFR Part 1005 (**Regulation E**) applies exclusively to accounts established primarily for personal, family, or household purposes.
- All Meridian Treasury, SMB, Mid-Market, and Enterprise accounts carry `account_class = COMMERCIAL`.
- Agents must **not** promise statutory 10-business-day Regulation E provisional credits, $50 consumer liability caps, or 45/90-day Reg E investigation timelines in written responses to commercial clients.
- Citing consumer statutory rights to a commercial entity creates binding promissory estoppel exposure for the bank.

## Truth in Lending (Regulation Z) Commercial Threshold
Under 12 CFR § 1026.3(a), extensions of credit primarily for business, commercial, or agricultural purposes are exempt from consumer Regulation Z billing error resolution procedures, except regarding unauthorized-use liability caps where a corporate program issues fewer than 10 employee cards (`card_program_size < 10`). Even when unauthorized liability protection applies, provisional credit issuance remains governed by `POL-CC-2026-04`.
