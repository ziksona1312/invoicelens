# InvoiceLens evaluation report

Dataset: 300 synthetic invoices, seed 42.
Ground truth comes from the generator; the extractor never sees it.

## Decisions

| Metric | Value |
| --- | ---: |
| Decision agrees with expected | 70.7% (212/300) |
| Straight-through rate (auto-approved) | 47.3% (142/300) |
| Approval precision (clean and fully correct) | 84.5% (120/142) |
| False approvals (defective invoice approved) | 4 |
| Clean invoices sent to review | 84/222 |

## Field accuracy by noise level

| Group | Docs | vendor | invoice_number | date | currency | subtotal | vat | total | line_count | All fields |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clean | 102 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| degraded | 89 | 96.6% | 68.5% | 94.4% | 95.5% | 83.1% | 74.2% | 89.9% | 33.7% | 14.6% |
| scanned | 109 | 99.1% | 94.5% | 100.0% | 100.0% | 93.6% | 96.3% | 98.2% | 66.1% | 56.0% |

## Field accuracy by template

| Group | Docs | vendor | invoice_number | date | currency | subtotal | vat | total | line_count | All fields |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| classic_en | 85 | 100.0% | 97.6% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 74.1% | 72.9% |
| compact_en | 73 | 95.9% | 68.5% | 100.0% | 94.5% | 100.0% | 93.2% | 97.3% | 71.2% | 53.4% |
| sr_racun | 69 | 100.0% | 91.3% | 97.1% | 100.0% | 89.9% | 87.0% | 97.1% | 66.7% | 53.6% |
| sr_standard | 73 | 98.6% | 95.9% | 95.9% | 100.0% | 79.5% | 82.2% | 90.4% | 58.9% | 52.1% |

## Defect detection

| Injected defect | Docs | Sent to review |
| --- | ---: | ---: |
| total_mismatch | 11 | 90.9% (10/11) |
| vat_mismatch | 19 | 89.5% (17/19) |
| unknown_vendor | 26 | 100.0% (26/26) |
| duplicate | 22 | 95.5% (21/22) |

## Why clean invoices went to review (false alarms)

| Reason | Count |
| --- | ---: |
| line_sum_mismatch | 51 |
| total_mismatch | 32 |
| vat_mismatch | 30 |
| low_confidence | 12 |
| missing_fields | 11 |
| duplicate | 1 |
