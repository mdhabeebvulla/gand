---
rule_id: R002_FEHBP_BROKER
placeholders:
  - Policy.PolicyState
  - fehbp_address.MailingAddress
---

For Federal Employees Health Benefit Program accounts in the state of {{Policy.PolicyState}}, Grievance and Appeal request must be sent in writing.

Advise the caller to send their grievance and/or appeal request to:

{{fehbp_address.MailingAddress}}

In the request the **Broker** must include their Identification Number, the reason for their complaint and their expected resolution to the complaint.
