#!/usr/bin/env python3
"""Pilot: treg.companies.enrich coverage on a CSLB company sample.

Requires a valid team agent token (env `treg` / `TREG_TOKEN`).
Hard stop without --confirm-spend (lead-scrape gates).

Example:
  python scripts/pilot_cslb_treg_companies_enrich.py \\
    --sample artifacts/cslb-treg-enrich/sample100.json \\
    --confirm-spend 5
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


ENDPOINT = "treg.companies.enrich"
CALL = f"https://treg.to/call/{ENDPOINT}"


def token() -> str:
    t = (os.environ.get("treg") or os.environ.get("TREG_TOKEN") or "").strip()
    if not t:
        raise SystemExit("Set treg / TREG_TOKEN to a valid team agent key")
    return t


def call_enrich(tok: str, body: dict, max_cost: float) -> tuple[dict, dict]:
    hdrs = {
        "X-Treg-Token": tok,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Treg-Route-Max-Cost": str(max_cost),
        "X-Treg-Route-Waterfall": "0",
    }
    req = urllib.request.Request(CALL, data=json.dumps(body).encode(), method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            meta = {
                "status": resp.status,
                "cost_micro": int(resp.headers.get("X-Treg-Cost-Micro") or 0),
                "served_by": resp.headers.get("X-Treg-Served-By"),
                "call_id": resp.headers.get("X-Treg-Call-Id"),
            }
            raw = resp.read().decode()
            return (json.loads(raw) if raw else {}), meta
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:500]}") from e


def hit(payload: dict) -> bool:
    out = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(out, dict):
        return False
    # catalog miss: output.name == null
    return bool(out.get("name") or out.get("domain") or out.get("website"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True, help="JSON list of CSLB company rows")
    ap.add_argument("--confirm-spend", type=float, required=True, help="Hard USD cap")
    ap.add_argument("--max-cost", type=float, default=0.05, help="Per-call X-Treg-Route-Max-Cost")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--out", default="/tmp/cslb_treg_enrich/results.jsonl")
    args = ap.parse_args()

    rows = json.loads(Path(args.sample).read_text())[: args.limit]
    tok = token()
    # Auth probe
    try:
        call_enrich(tok, {"domain": "stripe.com"}, max_cost=min(args.max_cost, 0.01))
    except RuntimeError as e:
        raise SystemExit(
            f"Treg /call/ auth failed before pilot: {e}\n"
            "Refresh the team agent key (catalog works without auth; /call/ needs a live key)."
        ) from e

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    spent_micro = 0
    cap_micro = int(args.confirm_spend * 1_000_000)
    stats = {"n": 0, "hits": 0, "misses": 0, "errors": 0, "with_domain_out": 0, "providers": {}}

    with open(args.out, "w") as fh:
        for r in rows:
            if spent_micro >= cap_micro:
                print(f"STOP at spend cap ${args.confirm_spend:.2f}")
                break
            body: dict = {}
            if r.get("company_domain"):
                body["domain"] = r["company_domain"]
            elif r.get("website"):
                body["website"] = r["website"]
            else:
                body["name"] = r.get("enrich_query_name") or r.get("enrich_name") or r.get("business_name")
            stats["n"] += 1
            try:
                payload, meta = call_enrich(tok, body, args.max_cost)
                spent_micro += meta["cost_micro"]
                ok = hit(payload)
                if ok:
                    stats["hits"] += 1
                    out = payload.get("output") or {}
                    if out.get("domain") or out.get("website"):
                        stats["with_domain_out"] += 1
                else:
                    stats["misses"] += 1
                prov = meta.get("served_by") or "unknown"
                stats["providers"][prov] = stats["providers"].get(prov, 0) + 1
                fh.write(
                    json.dumps(
                        {
                            "license_no": r.get("license_no"),
                            "business_name": r.get("business_name"),
                            "request": body,
                            "hit": ok,
                            "meta": meta,
                            "output": (payload.get("output") if isinstance(payload, dict) else None),
                            "_treg": (payload.get("_treg") if isinstance(payload, dict) else None),
                        }
                    )
                    + "\n"
                )
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                fh.write(
                    json.dumps(
                        {
                            "license_no": r.get("license_no"),
                            "business_name": r.get("business_name"),
                            "request": body,
                            "error": str(e)[:400],
                        }
                    )
                    + "\n"
                )
            time.sleep(args.sleep)

    summary = {
        **stats,
        "spent_usd": round(spent_micro / 1_000_000, 6),
        "confirm_spend": args.confirm_spend,
        "hit_rate": round(stats["hits"] / stats["n"], 4) if stats["n"] else 0,
        "domain_rate": round(stats["with_domain_out"] / stats["n"], 4) if stats["n"] else 0,
        "out": args.out,
    }
    Path(args.out).with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
