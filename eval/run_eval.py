"""Measure the pipeline against the ground truth of a synthetic dataset.

    python -m eval.run_eval --data data/synth --report eval/report.md

The extractor never sees the ground truth; it is only used here, for scoring.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

from app.models import Extracted
from app.pipeline import decide, extract
from app.validation.rules import Context, normalize_vendor

FIELDS = ["vendor", "invoice_number", "date", "currency", "subtotal", "vat", "total", "line_count"]
REF_DATE = date(2026, 11, 15)  # fixed so the report does not change from day to day


def field_correct(name: str, ex: Extracted, truth: dict) -> bool:
    if name == "line_count":
        return len(ex.lines) == truth["line_count"]
    got, want = getattr(ex, name), truth[name]
    if name == "vendor":
        return got is not None and normalize_vendor(got) == normalize_vendor(want)
    if name in ("subtotal", "vat", "total"):
        if got is None or want is None:
            return got is None and want is None
        return abs(got - want) < 0.005
    return got == want


def _extract_one(path: str) -> Extracted:
    return extract(path)


def pct(ok: int, n: int) -> str:
    return f"{100 * ok / n:.1f}%" if n else "n/a"


def run(data: Path) -> dict:
    manifest = json.loads((data / "manifest.json").read_text())
    ids = manifest["documents"]
    truths = {i: json.loads((data / f"{i}.json").read_text()) for i in ids}

    with ProcessPoolExecutor() as pool:  # OCR is the slow part, so extract in parallel
        extracted = list(pool.map(_extract_one, [str(data / f"{i}.pdf") for i in ids], chunksize=4))

    ctx = Context(known_vendors=set(manifest["known_vendors"]), today=REF_DATE)
    rows = []
    for doc_id, ex in zip(
        ids, extracted, strict=True
    ):  # validation is order-dependent (duplicates)
        truth = truths[doc_id]
        result = decide(ex, ctx)
        correct = {f: field_correct(f, ex, truth) for f in FIELDS}
        rows.append(
            {
                "id": doc_id,
                "truth": truth,
                "result": result,
                "correct": correct,
                "all_correct": all(correct.values()),
            }
        )
    return {"rows": rows, "n": len(rows)}


def group_table(rows: list[dict], key) -> list[str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    header = "| Group | Docs | " + " | ".join(FIELDS) + " | All fields |"
    sep = "| --- | ---: | " + " | ".join("---:" for _ in FIELDS) + " | ---: |"
    out = [header, sep]
    for name in sorted(groups):
        g = groups[name]
        cells = [pct(sum(r["correct"][f] for r in g), len(g)) for f in FIELDS]
        out.append(
            f"| {name} | {len(g)} | "
            + " | ".join(cells)
            + f" | {pct(sum(r['all_correct'] for r in g), len(g))} |"
        )
    return out


def build_report(res: dict, seed: int | None) -> str:
    rows = res["rows"]
    n = res["n"]
    approved = [r for r in rows if r["result"].decision == "approved"]
    exp_approved = [r for r in rows if r["truth"]["expected_decision"] == "approved"]
    agree = sum(r["result"].decision == r["truth"]["expected_decision"] for r in rows)
    # An approval is "safe" only if the invoice was really clean AND every field was read right.
    safe = [
        r for r in approved if r["truth"]["expected_decision"] == "approved" and r["all_correct"]
    ]
    false_approvals = [r for r in approved if r["truth"]["expected_decision"] != "approved"]

    clean_to_review = sum(r["result"].decision != "approved" for r in exp_approved)

    lines = [
        "# InvoiceLens evaluation report",
        "",
        f"Dataset: {n} synthetic invoices" + (f", seed {seed}" if seed is not None else "") + ".",
        "Ground truth comes from the generator; the extractor never sees it.",
        "",
        "## Decisions",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Decision agrees with expected | {pct(agree, n)} ({agree}/{n}) |",
        f"| Straight-through rate (auto-approved) | {pct(len(approved), n)} "
        f"({len(approved)}/{n}) |",
        f"| Approval precision (clean and fully correct) | {pct(len(safe), len(approved))} "
        f"({len(safe)}/{len(approved)}) |",
        f"| False approvals (defective invoice approved) | {len(false_approvals)} |",
        f"| Clean invoices sent to review | {clean_to_review}/{len(exp_approved)} |",
        "",
        "## Field accuracy by noise level",
        "",
        *group_table(rows, lambda r: r["truth"]["noise"]),
        "",
        "## Field accuracy by template",
        "",
        *group_table(rows, lambda r: r["truth"]["template"]),
        "",
        "## Defect detection",
        "",
        "| Injected defect | Docs | Sent to review |",
        "| --- | ---: | ---: |",
    ]
    for defect in ["total_mismatch", "vat_mismatch", "unknown_vendor", "duplicate"]:
        g = [r for r in rows if r["truth"]["defect"] == defect]
        caught = sum(r["result"].decision != "approved" for r in g)
        lines.append(f"| {defect} | {len(g)} | {pct(caught, len(g))} ({caught}/{len(g)}) |")

    reasons: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["truth"]["expected_decision"] == "approved" and r["result"].decision != "approved":
            for reason in r["result"].reasons:
                reasons[reason.split(":")[0]] += 1
    lines += ["", "## Why clean invoices went to review (false alarms)", ""]
    if reasons:
        lines += ["| Reason | Count |", "| --- | ---: |"]
        lines += [f"| {k} | {v} |" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/synth"))
    parser.add_argument("--report", type=Path, default=Path("eval/report.md"))
    args = parser.parse_args()
    manifest = json.loads((args.data / "manifest.json").read_text())
    res = run(args.data)
    report = build_report(res, manifest.get("seed"))
    args.report.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
