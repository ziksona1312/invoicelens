# ADR 0001: Rules first, measured against ground truth

Status: accepted (2026-11-15)

## Context

Invoices must be read and checked before payment. A wrong approval costs money; a needless
review costs a few minutes of someone's time. The extractor has to be explainable to the people
who own the process.

## Decision

- Extraction uses labelled regular expressions and line-based parsing. Every field carries a
  confidence: 1.0 next to a clear label, 0.5 when a fallback guessed it.
- Validation is a list of business rules (sums, VAT, known vendor, date range, duplicates).
  Any rule that fires sends the invoice to human review.
- Quality is measured, not assumed: a synthetic generator produces invoices with known ground
  truth, and `eval/run_eval.py` reports field accuracy, straight-through rate and false approvals.

## Consequences

- The system is conservative: it prefers a false alarm to a false approval.
- Every decision can be traced to a rule.
- An LLM fallback can be added later for low-confidence fields, and judged on the same report.
