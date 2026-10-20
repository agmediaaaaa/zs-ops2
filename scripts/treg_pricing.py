#!/usr/bin/env python3
"""Catalog-based Treg cost quotes for the Cheap Scrape path (Icypeas → Blitz).

Never invent flat averages — rates here are defaults from the catalog and can
be overridden. Prefer live `treg catalog get` when available.

Examples:
  python scripts/treg_pricing.py --pull 100 --hit-rate 0.45
  python scripts/treg_pricing.py --ready-target 200 --rows-per-ready 4 --attempts-per-ready 2
"""
from __future__ import annotations

import argparse
import json
import sys

# Defaults from treg catalog (verify with `treg catalog get` before large runs)
ICYPEAS_SEARCH_PER_RESULT = 0.00038
BLITZ_EMAIL_PER_SUCCESS = 0.000495
MV_VERIFY_PER_SUCCESS = 0.00178


def quote_pull_n(
    pull: int,
    hit_rate: float,
    search_unit: float = ICYPEAS_SEARCH_PER_RESULT,
    email_unit: float = BLITZ_EMAIL_PER_SUCCESS,
    verify: bool = False,
    verify_unit: float = MV_VERIFY_PER_SUCCESS,
) -> dict:
    """Pull-N model: bill for N search rows; email only on successes."""
    search_usd = pull * search_unit
    expected_hits = pull * hit_rate
    email_usd = expected_hits * email_unit
    verify_usd = (expected_hits * verify_unit) if verify else 0.0
    expected = search_usd + email_usd + verify_usd
    # max: every pulled row returns a billable email (+ verify)
    max_usd = pull * search_unit + pull * email_unit + (pull * verify_unit if verify else 0.0)
    return {
        "model": "pull_n",
        "pull": pull,
        "hit_rate_assumed": hit_rate,
        "expected_ready": round(expected_hits, 1),
        "units": {
            "icypeas.people.search": search_unit,
            "blitzapi.people.email.find": email_unit,
            **({"millionverifier.people.email.verify": verify_unit} if verify else {}),
        },
        "search_usd": round(search_usd, 6),
        "email_usd": round(email_usd, 6),
        "verify_usd": round(verify_usd, 6),
        "expected_usd": round(expected, 6),
        "max_usd": round(max_usd, 6),
        "recommended_cap_usd": round(max_usd * 1.4, 6),
        "est_cost_per_1k_ready_usd": round((expected / max(expected_hits, 1e-9)) * 1000, 2),
        "note": "Coverage = ready/pulled; ready < pulled is correct. Ask for --confirm-spend.",
    }


def quote_ready_target(
    ready: int,
    rows_per_ready: float,
    attempts_per_ready: float,
    search_unit: float = ICYPEAS_SEARCH_PER_RESULT,
    email_unit: float = BLITZ_EMAIL_PER_SUCCESS,
) -> dict:
    """Legacy estimate when planning around ready count (prefer pull-N)."""
    search_rows = ready * rows_per_ready
    email_attempts = ready * attempts_per_ready
    # email bills on success ≈ ready (1 success per ready)
    search_usd = search_rows * search_unit
    email_usd = ready * email_unit
    expected = search_usd + email_usd
    max_usd = search_rows * search_unit + email_attempts * email_unit
    return {
        "model": "ready_target_estimate",
        "ready_target": ready,
        "rows_per_ready": rows_per_ready,
        "attempts_per_ready": attempts_per_ready,
        "search_usd": round(search_usd, 6),
        "email_usd": round(email_usd, 6),
        "expected_usd": round(expected, 6),
        "max_usd": round(max_usd, 6),
        "recommended_cap_usd": round(max_usd * 1.4, 6),
        "est_cost_per_1k_ready_usd": round((expected / ready) * 1000, 2),
        "note": "Prefer --pull N. This mode is only for rough planning. Ask for --confirm-spend.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Treg Cheap Scrape cost quote (catalog-based)")
    ap.add_argument("--pull", type=int, default=0, help="Pull-N people from Icypeas")
    ap.add_argument("--hit-rate", type=float, default=0.45, help="Assumed Blitz success rate on pulled")
    ap.add_argument("--ready-target", type=int, default=0, help="Optional ready-based estimate")
    ap.add_argument("--rows-per-ready", type=float, default=4.0)
    ap.add_argument("--attempts-per-ready", type=float, default=2.0)
    ap.add_argument("--verify", action="store_true", help="Include MillionVerifier in quote")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.pull <= 0 and args.ready_target <= 0:
        ap.print_help()
        print("\nProvide --pull N and/or --ready-target N", file=sys.stderr)
        sys.exit(2)

    out: dict = {"pathway": "icypeas.people.search → blitzapi.people.email.find"}
    if args.pull > 0:
        out["pull_n"] = quote_pull_n(args.pull, args.hit_rate, verify=args.verify)
    if args.ready_target > 0:
        out["ready_target"] = quote_ready_target(
            args.ready_target, args.rows_per_ready, args.attempts_per_ready
        )

    if args.json:
        print(json.dumps(out, indent=2))
        return

    print("Pathway: Icypeas people.search → Blitz email.find")
    print("(Rates from catalog defaults — re-check with `treg catalog get` before large runs)\n")
    if "pull_n" in out:
        q = out["pull_n"]
        print(f"=== Pull-N  pull={q['pull']}  hit_rate={q['hit_rate_assumed']} ===")
        print(f"  expected_ready:          {q['expected_ready']}")
        print(f"  search_usd:              ${q['search_usd']:.4f}")
        print(f"  email_usd:               ${q['email_usd']:.4f}")
        if q["verify_usd"]:
            print(f"  verify_usd:              ${q['verify_usd']:.4f}")
        print(f"  expected_usd:            ${q['expected_usd']:.4f}")
        print(f"  max_usd:                 ${q['max_usd']:.4f}")
        print(f"  recommended_cap_usd:     ${q['recommended_cap_usd']:.4f}  (max × 1.4)")
        print(f"  est $/1k ready:          ${q['est_cost_per_1k_ready_usd']:.2f}")
        print()
    if "ready_target" in out:
        q = out["ready_target"]
        print(f"=== Ready-target estimate  ready={q['ready_target']} ===")
        print(f"  expected_usd:            ${q['expected_usd']:.4f}")
        print(f"  max_usd:                 ${q['max_usd']:.4f}")
        print(f"  recommended_cap_usd:     ${q['recommended_cap_usd']:.4f}")
        print(f"  est $/1k ready:          ${q['est_cost_per_1k_ready_usd']:.2f}")
        print()
    print('Ask: What hard cost cap should I use? Reply with `--confirm-spend <USD>`.')
    print("Do not spend until confirm.")


if __name__ == "__main__":
    main()
