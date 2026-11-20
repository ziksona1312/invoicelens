"""Send generated invoices to the running service and compare its decisions with ground truth.

make data && docker compose up -d --build
python -m tools.load_demo --n 50
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import httpx

DONE = {"approved", "review", "rejected", "failed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--data", type=Path, default=Path("data/synth"))
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for the worker")
    args = parser.parse_args()

    ids = json.loads((args.data / "manifest.json").read_text())["documents"][: args.n]
    sent: dict[str, str] = {}  # document id -> generator id
    reused = 0
    with httpx.Client(base_url=args.api, timeout=30) as client:
        started = time.perf_counter()
        for gen_id in ids:
            pdf = (args.data / f"{gen_id}.pdf").read_bytes()
            r = client.post("/documents", files={"file": (f"{gen_id}.pdf", pdf, "application/pdf")})
            r.raise_for_status()
            reused += r.status_code == 200
            sent[r.json()["id"]] = gen_id
        took = time.perf_counter() - started
        print(f"Uploaded {len(ids)} files ({reused} already known) in {took:.1f} s")

        results: dict[str, dict] = {}
        deadline = time.time() + args.timeout
        while len(results) < len(sent) and time.time() < deadline:
            for doc_id in sent.keys() - results.keys():
                body = client.get(f"/documents/{doc_id}").json()
                if body["status"] in DONE:
                    results[doc_id] = body
            print(f"\r{len(results)}/{len(sent)} processed", end="", flush=True)
            if len(results) < len(sent):
                time.sleep(1)
        print(
            f"\nAll done in {time.perf_counter() - started:.1f} s"
            if len(results) == len(sent)
            else f"\nTimed out: {len(sent) - len(results)} still processing"
        )

    statuses = Counter(b["status"] for b in results.values())
    agree = clean = clean_auto = 0
    for doc_id, body in results.items():
        truth = json.loads((args.data / f"{sent[doc_id]}.json").read_text())
        agree += body["status"] == truth["expected_decision"]
        if truth["expected_decision"] == "approved":
            clean += 1
            clean_auto += body["status"] == "approved"

    print("\nStatus counts:", dict(statuses))
    print(f"Decision agrees with ground truth: {agree}/{len(results)}")
    print(f"Clean invoices approved with no person involved: {clean_auto}/{clean}")
    print(f"Review queue: {args.api}/review")


if __name__ == "__main__":
    main()
