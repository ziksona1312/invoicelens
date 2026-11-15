# ADR 0002: OCR preprocessing (deskew + median filter at 200 dpi)

Status: accepted (2026-11-15)

## Context

Badly scanned invoices (rotated up to 2.5 degrees, blurred, noisy, 130 dpi) were read poorly by
Tesseract. Several preprocessing options were compared on the 89 "degraded" documents of the
seed-42 dataset.

| Variant | invoice_number | subtotal | vat | total | line_count | Time (89 docs, 2 cores) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Grayscale + autocontrast, 200 dpi | 60% | 76% | 65% | 85% | 31% | 20 s |
| + deskew | 70% | 84% | 62% | 84% | 39% | 29 s |
| + deskew + median filter (chosen) | 69% | 83% | 74% | 90% | 34% | 44 s |
| + deskew, global threshold | 17% | 30% | 4% | 74% | 0% | 25 s |
| + deskew, 250 dpi | 60% | 75% | 61% | 83% | 27% | 36 s |
| + deskew + median, 250 dpi | 67% | 80% | 76% | 87% | 27% | 56 s |

## Decision

Deskew by maximising the variance of row sums over -3..3 degrees, then a 3x3 median filter, at
200 dpi. It gave the best total and VAT accuracy, which drive the approval decision.

## Consequences

- Degraded scans remain the weak spot (line items especially). Next candidates: adaptive
  thresholding, Tesseract `--psm` per region, or an LLM fallback on low-confidence fields.
- A global threshold destroys faded text; do not use it.
