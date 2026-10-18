#!/usr/bin/env python3
"""Pull-N staged pipeline helpers (locked for all future list runs).

Semantics
---------
When the user asks for N prospects:
  1. Pull N people from Icypeas people search (post ICP/title filters)
  2. Email-find that fixed batch (Supabase cache first)
  3. MV-verify found emails (concurrent)
  4. Bulk upload to Supabase with desc/loc/etc.

Ready emails = whatever validates from those N. Do NOT keep paging until N ready.

Email find excludes Icypeas (and AI Ark) unless WITH_ICYPEAS_EMAIL is set.
"""
from __future__ import annotations

# Route headers for treg.people.email.find / provider finds
EMAIL_ROUTE_EXCLUDE = "aiark,icypeas"
EMAIL_ROUTE_EXCLUDE_WITH_ICYPEAS = "aiark"  # only when --with-icypeas-email

# Concurrent workers
FIND_WORKERS = 32
MV_WORKERS = 50
SUPABASE_UPSERT_BATCH = 100


def email_exclude_header(*, with_icypeas_email: bool = False) -> str:
    return (
        EMAIL_ROUTE_EXCLUDE_WITH_ICYPEAS
        if with_icypeas_email
        else EMAIL_ROUTE_EXCLUDE
    )


def coverage(ready: int, pulled: int) -> float:
    if pulled <= 0:
        return 0.0
    return round(ready / pulled, 4)


def report_pull_n(
    *,
    pull: int,
    pulled: int,
    ready: int,
    skipped_cache: int,
    plusvibe_excluded: int,
    find_attempts: int,
    find_hits: int,
    spent_usd: float,
    email_order: list[str],
) -> dict:
    """Canonical end-of-run metrics for pull-N builders."""
    return {
        "model": "pull_n",
        "pull_requested": pull,
        "pulled": pulled,
        "ready": ready,
        "coverage": coverage(ready, pulled),
        "skipped_supabase_cache": skipped_cache,
        "plusvibe_excluded": plusvibe_excluded,
        "find_attempts": find_attempts,
        "find_hits": find_hits,
        "spent_usd": round(spent_usd, 6),
        "email_order": email_order,
        "icypeas_email": False,
        "note": "N = Icypeas people pulled; ready = valid emails from that batch",
    }
