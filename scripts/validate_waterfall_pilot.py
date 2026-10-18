#!/usr/bin/env python3
"""Validate cost-exact waterfall quotes for a 500-row pilot.

Without TREG_TOKEN: dry-run catalog quotes + structural assertions.
With TREG_TOKEN: also probe free counts and one cheap catalog access path.

Does NOT spend on email find/verify unless --live-spend is passed with
--confirm-spend (kept off by default for CI/safety).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import treg_pricing

OUT = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/waterfall-pilot"))
PILOT_N = 500


def assert_quote(q: treg_pricing.RunQuote, *, label: str) -> list[str]:
    errs: list[str] = []
    if not q.lines:
        errs.append(f"{label}: empty quote lines")
    # ContactOut must never appear in default enrich quote
    for ln in q.lines:
        if "contactout" in ln.endpoint.lower():
            errs.append(f"{label}: ContactOut present in quote ({ln.endpoint})")
        if ln.line_usd < 0:
            errs.append(f"{label}: negative line_usd on {ln.endpoint}")
        if ln.volume < 0:
            errs.append(f"{label}: negative volume on {ln.endpoint}")
    if q.expected_usd < 0 or q.max_usd < 0:
        errs.append(f"{label}: negative totals")
    if q.max_usd + 1e-9 < q.expected_usd:
        errs.append(
            f"{label}: max_usd {q.max_usd} < expected_usd {q.expected_usd}"
        )
    if q.recommended_cap_usd + 1e-9 < q.max_usd:
        errs.append(f"{label}: recommended_cap below max")
    # Find-first default should include Blitz (or find stages)
    stages = {ln.stage for ln in q.lines}
    if label.startswith("enrich") and "find_blitz" not in stages and "cache" not in stages:
        errs.append(f"{label}: missing find-first stages")
    return errs


def dry_run_suite() -> dict:
    errs: list[str] = []
    results: dict = {"checks": []}

    # Refresh rates once
    rates = treg_pricing.get_rates(
        [
            "icypeas.companies.search",
            "aiark.companies.search",
            "blitzapi.people.email.find",
            "quickenrich.people.email.find",
            "trykitt.people.email.find",
            "millionverifier.people.email.verify",
            "icypeas.bulk.search",
            "contactout.people.email.verify",
        ],
        force_refresh=True,
    )
    for eid, rate in rates.items():
        results["checks"].append(
            {
                "endpoint": eid,
                "usd": rate.unit_usd,
                "type": rate.billing_type,
                "source": rate.source,
            }
        )
        if eid != "contactout.people.email.verify" and rate.billing_type != "free":
            if rate.unit_usd <= 0:
                errs.append(f"paid endpoint {eid} has usd={rate.unit_usd}")

    enrich = treg_pricing.quote_run(mode="enrich", pending_leads=PILOT_N)
    errs.extend(assert_quote(enrich, label="enrich_500"))
    enrich.print_table()

    enrich_pm = treg_pricing.quote_run(
        mode="enrich", pending_leads=PILOT_N, with_pattern_mv=True
    )
    errs.extend(assert_quote(enrich_pm, label="enrich_500_pattern_mv"))
    # pattern mode should have a pattern_verify line
    if not any(ln.stage == "pattern_verify" for ln in enrich_pm.lines):
        errs.append("enrich_500_pattern_mv: missing pattern_verify stage")

    discover = treg_pricing.quote_run(mode="discover", companies=PILOT_N)
    errs.extend(assert_quote(discover, label="discover_500"))
    # discovery should price ~500 * 0.00038 for icypeas default
    disc_lines = [ln for ln in discover.lines if ln.stage == "discover_companies"]
    if disc_lines:
        expected_line = round(PILOT_N * disc_lines[0].unit_usd, 6)
        if abs(disc_lines[0].line_usd - expected_line) > 1e-6:
            errs.append(
                f"discover line_usd {disc_lines[0].line_usd} != {expected_line}"
            )

    full = treg_pricing.quote_run(
        mode="full", companies=PILOT_N, people=PILOT_N, pending_leads=PILOT_N
    )
    errs.extend(assert_quote(full, label="full_500"))

    # Simulated ledger: pretend Blitz hit 55% of post-cache pool at catalog rate
    blitz = rates["blitzapi.people.email.find"]
    after_cache = int(round(PILOT_N * 0.85))
    sim_hits = int(round(after_cache * 0.55))
    sim_cost = sim_hits * blitz.unit_usd
    # Variance vs enrich expected find_blitz line
    blitz_line = next((ln for ln in enrich.lines if ln.stage == "find_blitz"), None)
    sim_variance = None
    if blitz_line:
        sim_variance = round(sim_cost - blitz_line.line_usd, 6)

    results.update(
        {
            "pilot_n": PILOT_N,
            "enrich_quote": enrich.to_dict(),
            "enrich_pattern_mv_quote": enrich_pm.to_dict(),
            "discover_quote": discover.to_dict(),
            "full_quote": full.to_dict(),
            "simulated_blitz_hits": sim_hits,
            "simulated_blitz_cost_usd": round(sim_cost, 6),
            "simulated_blitz_variance_vs_quote": sim_variance,
            "errors": errs,
            "ok": not errs,
        }
    )
    return results


def live_free_probes() -> dict:
    """Optional: free count probes when TREG_TOKEN is set."""
    import discover_companies as disc

    disc.TOKEN = disc.load_treg_token()
    q = {
        "industry": {"include": ["Software Development"]},
        "headcount": {">=": 11, "<=": 50},
        "location": {"include": ["United States"]},
    }
    t0 = time.time()
    tam = disc.free_company_count(q)
    elapsed = time.time() - t0
    return {
        "tam_software_11_50_us": tam,
        "elapsed_s": round(elapsed, 2),
        "query": q,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--live-counts", action="store_true", help="Free Treg count probe")
    args = p.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    report = dry_run_suite()

    if args.live_counts:
        try:
            report["live_counts"] = live_free_probes()
        except SystemExit as e:
            report["live_counts"] = {"skipped": str(e)}
        except Exception as e:
            report["live_counts"] = {"error": str(e)}
            report["ok"] = False
            report["errors"].append(f"live_counts: {e}")

    out_path = OUT / "pilot_500_validation.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(json.dumps({"ok": report["ok"], "errors": report["errors"], "out": str(out_path)}, indent=2))
    if report.get("enrich_quote"):
        print(
            f"\nPilot {PILOT_N} enrich: expected "
            f"${report['enrich_quote']['expected_usd']:.4f} "
            f"max ${report['enrich_quote']['max_usd']:.4f} "
            f"cap ${report['enrich_quote']['recommended_cap_usd']:.2f}"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
