#!/usr/bin/env python3
"""Catalog-backed Treg pricing: rate cache, billing units, run quotes.

Fetches live rates from https://treg.to/catalog/search (no auth required for
search). Falls back to a baked-in rate card when the catalog is unreachable.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

CATALOG_SEARCH = "https://treg.to/catalog/search"
DEFAULT_CACHE_PATH = Path(
    os.environ.get("TREG_PRICE_CACHE", "/tmp/treg_price_cache.json")
)
CACHE_TTL_S = int(os.environ.get("TREG_PRICE_CACHE_TTL", str(6 * 3600)))

# Baked-in fallbacks (catalog-verified 2026-10-18). Prefer live catalog.
FALLBACK_RATES: dict[str, dict[str, Any]] = {
    "icypeas.companies.search.count": {
        "type": "free",
        "usd": 0.0,
        "unit": "call",
    },
    "icypeas.companies.search": {
        "type": "per_result",
        "usd": 0.00038,
        "unit": "result",
    },
    "icypeas.people.search.count": {
        "type": "free",
        "usd": 0.0,
        "unit": "call",
    },
    "icypeas.people.search": {
        "type": "per_result",
        "usd": 0.00038,
        "unit": "result",
    },
    "aiark.companies.search": {
        "type": "per_success",
        "usd": 0.0005267,
        "unit": "found",
    },
    "leadsforge.people.search": {
        "type": "free",
        "usd": 0.0,
        "unit": "call",
    },
    "leadsforge.people.search.count": {
        "type": "free",
        "usd": 0.0,
        "unit": "call",
    },
    "blitzapi.people.email.find": {
        "type": "per_success",
        "usd": 0.000495,
        "unit": "record",
    },
    "quickenrich.people.email.find": {
        "type": "per_success",
        "usd": 0.004834,
        "unit": "call",
    },
    "trykitt.people.email.find": {
        "type": "per_success",
        "usd": 0.005,
        "unit": "call",
    },
    "millionverifier.people.email.verify": {
        "type": "per_success",
        "usd": 0.00178,
        "unit": "call",
    },
    "trykitt.people.email.verify": {
        "type": "per_success",
        "usd": 0.0015,
        "unit": "call",
    },
    "contactout.people.email.verify": {
        "type": "free",
        "usd": 0.0,
        "unit": "call",
    },
    "icypeas.bulk.search": {
        "type": "per_result",
        "usd": 0.019,
        "unit": "result",
    },
    "leadsforge.people.email.find.bulk": {
        "type": "per_success",
        "usd": 0.0245,
        "unit": "row",
    },
    "tomba.people.email.find": {
        "type": "per_success",
        "usd": 0.0089,
        "unit": "call",
    },
}

# Default find-first waterfall (ContactOut excluded).
DEFAULT_FIND_WATERFALL = [
    "blitzapi.people.email.find",
    "quickenrich.people.email.find",
    "trykitt.people.email.find",
]

DEFAULT_VERIFY = "millionverifier.people.email.verify"


@dataclass
class EndpointRate:
    endpoint: str
    billing_type: str  # free | per_call | per_result | per_success | per_page
    usd: float
    unit: str
    source: str = "fallback"  # live | cache | fallback
    checked: str | None = None
    hit_rate: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def unit_usd(self) -> float:
        return float(self.usd or 0.0)


@dataclass
class QuoteLine:
    endpoint: str
    stage: str
    billing_type: str
    unit_usd: float
    volume: int
    line_usd: float
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunQuote:
    mode: str
    lines: list[QuoteLine]
    expected_usd: float
    max_usd: float
    recommended_cap_usd: float
    assumptions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "lines": [ln.to_dict() for ln in self.lines],
            "expected_usd": round(self.expected_usd, 6),
            "max_usd": round(self.max_usd, 6),
            "recommended_cap_usd": round(self.recommended_cap_usd, 2),
            "assumptions": self.assumptions,
        }

    def print_table(self) -> None:
        print(f"\nQuote ({self.mode})")
        print(f"{'Stage':<18} {'Endpoint':<42} {'Unit$':>10} {'Vol':>6} {'Line$':>10}  Notes")
        print("-" * 110)
        for ln in self.lines:
            print(
                f"{ln.stage:<18} {ln.endpoint:<42} {ln.unit_usd:>10.6f} "
                f"{ln.volume:>6} {ln.line_usd:>10.4f}  {ln.notes}"
            )
        print("-" * 110)
        print(f"{'expected_usd':<18} ${self.expected_usd:.4f}")
        print(f"{'max_usd':<18} ${self.max_usd:.4f}")
        print(f"{'recommended_cap':<18} ${self.recommended_cap_usd:.2f} (max + 40%)")


def _normalize_billing_type(cost: dict[str, Any]) -> str:
    raw = (cost.get("type") or "per_call").lower()
    if raw in ("free", "zero"):
        return "free"
    if raw in ("per_result", "per_row", "per_found"):
        # per_found maps to per_success semantics for quoting
        if raw == "per_found":
            return "per_success"
        return "per_result"
    if raw in ("per_success", "per_hit"):
        return "per_success"
    if raw in ("per_page",):
        return "per_page"
    if raw in ("per_call", "flat", "call"):
        return "per_call"
    return raw


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_cache(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
    except Exception:
        pass


def fetch_endpoint_rate(
    endpoint: str,
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    ttl_s: int = CACHE_TTL_S,
    force_refresh: bool = False,
) -> EndpointRate:
    """Resolve unit price for one catalog endpoint id."""
    cache = _load_cache(cache_path)
    now = time.time()
    entry = cache.get(endpoint)
    if (
        not force_refresh
        and isinstance(entry, dict)
        and (now - float(entry.get("fetched_at") or 0)) < ttl_s
    ):
        return EndpointRate(
            endpoint=endpoint,
            billing_type=entry["billing_type"],
            usd=float(entry["usd"]),
            unit=entry.get("unit") or "call",
            source="cache",
            checked=entry.get("checked"),
            hit_rate=entry.get("hit_rate"),
            raw=entry.get("raw") or {},
        )

    rate: EndpointRate | None = None
    try:
        url = CATALOG_SEARCH + "?" + urllib.parse.urlencode({"q": endpoint})
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "zs-ops2-treg-pricing/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode() or "{}")
        hit = None
        for row in payload.get("results") or []:
            if row.get("id") == endpoint:
                hit = row
                break
        if hit:
            cost = hit.get("cost") or {}
            observed = hit.get("observed") or {}
            rate = EndpointRate(
                endpoint=endpoint,
                billing_type=_normalize_billing_type(cost),
                usd=float(cost.get("usd") if cost.get("usd") is not None else 0.0),
                unit=str(cost.get("unit") or "call"),
                source="live",
                checked=str(cost.get("checked") or hit.get("verified") or ""),
                hit_rate=(
                    float(observed["hit_rate"])
                    if observed.get("hit_rate") is not None
                    else None
                ),
                raw=hit,
            )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, KeyError):
        rate = None

    if rate is None:
        fb = FALLBACK_RATES.get(endpoint)
        if not fb:
            raise KeyError(f"No catalog rate or fallback for endpoint: {endpoint}")
        rate = EndpointRate(
            endpoint=endpoint,
            billing_type=_normalize_billing_type(fb),
            usd=float(fb["usd"]),
            unit=str(fb.get("unit") or "call"),
            source="fallback",
            checked=None,
            hit_rate=None,
        )

    cache[endpoint] = {
        "billing_type": rate.billing_type,
        "usd": rate.usd,
        "unit": rate.unit,
        "checked": rate.checked,
        "hit_rate": rate.hit_rate,
        "fetched_at": now,
        "source": rate.source,
        "raw": {
            "id": rate.raw.get("id"),
            "name": rate.raw.get("name"),
            "summary": rate.raw.get("summary"),
        }
        if rate.raw
        else {},
    }
    _save_cache(cache_path, cache)
    return rate


def get_rates(
    endpoints: Iterable[str],
    *,
    force_refresh: bool = False,
) -> dict[str, EndpointRate]:
    return {
        ep: fetch_endpoint_rate(ep, force_refresh=force_refresh) for ep in endpoints
    }


def line_cost(rate: EndpointRate, volume: int, *, assume_hit: bool = True) -> float:
    """Compute line USD for a volume of chargeable units."""
    if volume <= 0 or rate.billing_type == "free":
        return 0.0
    if rate.billing_type == "per_success" and not assume_hit:
        # Misses on per-success settle at $0; expected uses hit_rate separately.
        return 0.0
    return rate.unit_usd * volume


def quote_discovery(
    *,
    companies: int = 0,
    people: int = 0,
    company_endpoint: str = "icypeas.companies.search",
    people_endpoint: str = "icypeas.people.search",
    page_size: int = 100,
    include_counts: bool = True,
) -> list[QuoteLine]:
    """Quote company/people discovery (per-result × rows)."""
    lines: list[QuoteLine] = []
    if include_counts:
        if companies > 0:
            cr = fetch_endpoint_rate("icypeas.companies.search.count")
            lines.append(
                QuoteLine(
                    endpoint=cr.endpoint,
                    stage="discover_count",
                    billing_type=cr.billing_type,
                    unit_usd=cr.unit_usd,
                    volume=1,
                    line_usd=0.0,
                    notes="free count before paid pages",
                )
            )
        if people > 0:
            pr = fetch_endpoint_rate("icypeas.people.search.count")
            lines.append(
                QuoteLine(
                    endpoint=pr.endpoint,
                    stage="discover_count",
                    billing_type=pr.billing_type,
                    unit_usd=pr.unit_usd,
                    volume=1,
                    line_usd=0.0,
                    notes="free count before paid pages",
                )
            )

    if companies > 0:
        rate = fetch_endpoint_rate(company_endpoint)
        pages = max(1, (companies + page_size - 1) // page_size)
        lines.append(
            QuoteLine(
                endpoint=rate.endpoint,
                stage="discover_companies",
                billing_type=rate.billing_type,
                unit_usd=rate.unit_usd,
                volume=companies,
                line_usd=round(line_cost(rate, companies), 6),
                notes=f"~{pages} pages × {page_size} (parallel)",
            )
        )
    if people > 0:
        rate = fetch_endpoint_rate(people_endpoint)
        pages = max(1, (people + page_size - 1) // page_size)
        lines.append(
            QuoteLine(
                endpoint=rate.endpoint,
                stage="discover_people",
                billing_type=rate.billing_type,
                unit_usd=rate.unit_usd,
                volume=people,
                line_usd=round(line_cost(rate, people), 6),
                notes=f"~{pages} pages × {page_size} (parallel)",
            )
        )
    return lines


def quote_enrichment(
    *,
    pending_leads: int,
    with_pattern_mv: bool = False,
    cache_hit_rate: float = 0.15,
    blitz_share: float = 0.55,
    qe_share: float = 0.25,
    trykitt_share: float = 0.15,
    miss_share: float = 0.05,
    pattern_hit_rate: float = 0.35,
    verify_found: bool = True,
    bulk_spill_threshold: int = 100,
    bulk_endpoint: str = "icypeas.bulk.search",
) -> tuple[list[QuoteLine], dict[str, Any]]:
    """Quote find-first email enrichment (default) or optional pattern+MV.

    Expected cost weights hit rates across the waterfall.
    Max cost assumes every remaining lead pays the most expensive find + verify.
    """
    n = max(0, int(pending_leads))
    assumptions = {
        "pending_leads": n,
        "with_pattern_mv": with_pattern_mv,
        "cache_hit_rate": cache_hit_rate,
        "blitz_share": blitz_share,
        "qe_share": qe_share,
        "trykitt_share": trykitt_share,
        "miss_share": miss_share,
        "pattern_hit_rate": pattern_hit_rate,
        "verify_found": verify_found,
        "contactout": "excluded",
    }
    lines: list[QuoteLine] = []
    if n == 0:
        return lines, assumptions

    after_cache = int(round(n * (1.0 - cache_hit_rate)))
    lines.append(
        QuoteLine(
            endpoint="supabase.cache",
            stage="cache",
            billing_type="free",
            unit_usd=0.0,
            volume=n - after_cache,
            line_usd=0.0,
            notes=f"assumed {cache_hit_rate:.0%} cache hits",
        )
    )

    blitz = fetch_endpoint_rate("blitzapi.people.email.find")
    qe = fetch_endpoint_rate("quickenrich.people.email.find")
    tk = fetch_endpoint_rate("trykitt.people.email.find")
    mv = fetch_endpoint_rate(DEFAULT_VERIFY)

    if with_pattern_mv:
        pattern_attempts = after_cache
        pattern_hits = int(round(pattern_attempts * pattern_hit_rate))
        pattern_misses = pattern_attempts - pattern_hits
        lines.append(
            QuoteLine(
                endpoint=mv.endpoint,
                stage="pattern_verify",
                billing_type=mv.billing_type,
                unit_usd=mv.unit_usd,
                volume=pattern_attempts,
                line_usd=round(line_cost(mv, pattern_attempts), 6),
                notes=f"optional --with-pattern-mv; ~{pattern_hit_rate:.0%} hit",
            )
        )
        find_pool = pattern_misses
    else:
        find_pool = after_cache

    # Expected find mix on the remaining pool
    n_blitz = int(round(find_pool * blitz_share))
    n_qe = int(round(find_pool * qe_share))
    n_tk = int(round(find_pool * trykitt_share))
    n_miss = max(0, find_pool - n_blitz - n_qe - n_tk)

    for rate, vol, stage in (
        (blitz, n_blitz, "find_blitz"),
        (qe, n_qe, "find_quickenrich"),
        (tk, n_tk, "find_trykitt"),
    ):
        if vol <= 0:
            continue
        lines.append(
            QuoteLine(
                endpoint=rate.endpoint,
                stage=stage,
                billing_type=rate.billing_type,
                unit_usd=rate.unit_usd,
                volume=vol,
                line_usd=round(line_cost(rate, vol), 6),
                notes="expected hits (per-success)",
            )
        )

    found = n_blitz + n_qe + n_tk
    if verify_found and found > 0:
        # Blitz returns verified email; still budget MV for QE/Trykitt finds
        verify_vol = n_qe + n_tk
        if verify_vol > 0:
            lines.append(
                QuoteLine(
                    endpoint=mv.endpoint,
                    stage="verify_found",
                    billing_type=mv.billing_type,
                    unit_usd=mv.unit_usd,
                    volume=verify_vol,
                    line_usd=round(line_cost(mv, verify_vol), 6),
                    notes="MV on QE/Trykitt finds (Blitz already verified)",
                )
            )

    if n_miss >= bulk_spill_threshold:
        bulk = fetch_endpoint_rate(bulk_endpoint)
        lines.append(
            QuoteLine(
                endpoint=bulk.endpoint,
                stage="bulk_spill",
                billing_type=bulk.billing_type,
                unit_usd=bulk.unit_usd,
                volume=n_miss,
                line_usd=round(line_cost(bulk, n_miss), 6),
                notes=f"miss queue ≥{bulk_spill_threshold}",
            )
        )
    elif n_miss > 0:
        lines.append(
            QuoteLine(
                endpoint="(unresolved)",
                stage="find_miss",
                billing_type="free",
                unit_usd=0.0,
                volume=n_miss,
                line_usd=0.0,
                notes="below bulk threshold; leave unresolved",
            )
        )

    assumptions["find_pool"] = find_pool
    assumptions["expected_found"] = found
    assumptions["expected_miss"] = n_miss
    return lines, assumptions


def quote_run(
    *,
    mode: str = "enrich",
    companies: int = 0,
    people: int = 0,
    pending_leads: int = 0,
    with_pattern_mv: bool = False,
    company_endpoint: str = "icypeas.companies.search",
    people_endpoint: str = "icypeas.people.search",
    page_size: int = 100,
    buffer: float = 1.4,
    force_refresh: bool = False,
) -> RunQuote:
    """Build a full run quote with expected and max spend."""
    if force_refresh:
        # Warm cache for endpoints we will touch
        eps = [
            company_endpoint,
            people_endpoint,
            "icypeas.companies.search.count",
            "icypeas.people.search.count",
            *DEFAULT_FIND_WATERFALL,
            DEFAULT_VERIFY,
            "icypeas.bulk.search",
        ]
        get_rates(eps, force_refresh=True)

    lines: list[QuoteLine] = []
    assumptions: dict[str, Any] = {"buffer": buffer, "mode": mode}

    if companies or people:
        lines.extend(
            quote_discovery(
                companies=companies,
                people=people,
                company_endpoint=company_endpoint,
                people_endpoint=people_endpoint,
                page_size=page_size,
            )
        )

    enrich_n = pending_leads or people or 0
    if mode in ("enrich", "full", "pilot") and enrich_n > 0:
        elines, eass = quote_enrichment(
            pending_leads=enrich_n,
            with_pattern_mv=with_pattern_mv,
        )
        lines.extend(elines)
        assumptions.update(eass)

    expected = sum(ln.line_usd for ln in lines)

    # Max: discovery full rows + every post-cache lead pays Trykitt find + MV verify
    max_usd = 0.0
    for ln in lines:
        if ln.stage.startswith("discover"):
            max_usd += ln.line_usd
    after_cache = int(
        round(
            enrich_n
            * (1.0 - float(assumptions.get("cache_hit_rate", 0.15)))
        )
    ) if enrich_n else 0
    if after_cache > 0:
        tk = fetch_endpoint_rate("trykitt.people.email.find")
        mv = fetch_endpoint_rate(DEFAULT_VERIFY)
        if with_pattern_mv:
            max_usd += mv.unit_usd * after_cache  # every pattern verify
            # worst: all pattern miss → trykitt + verify
            max_usd += (tk.unit_usd + mv.unit_usd) * after_cache
        else:
            max_usd += (tk.unit_usd + mv.unit_usd) * after_cache

    cap = round(max_usd * buffer, 2)
    return RunQuote(
        mode=mode,
        lines=lines,
        expected_usd=expected,
        max_usd=max_usd,
        recommended_cap_usd=cap,
        assumptions=assumptions,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Quote Treg discovery/enrichment spend")
    p.add_argument("--companies", type=int, default=0)
    p.add_argument("--people", type=int, default=0)
    p.add_argument("--pending-leads", type=int, default=0)
    p.add_argument("--mode", default="full", choices=["discover", "enrich", "full", "pilot"])
    p.add_argument("--with-pattern-mv", action="store_true")
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--refresh", action="store_true", help="Force catalog refresh")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    mode = args.mode
    if mode == "discover":
        pending = 0
    else:
        pending = args.pending_leads or args.people

    q = quote_run(
        mode=mode,
        companies=args.companies,
        people=args.people if mode != "enrich" else 0,
        pending_leads=pending,
        with_pattern_mv=args.with_pattern_mv,
        page_size=args.page_size,
        force_refresh=args.refresh,
    )
    if args.json:
        print(json.dumps(q.to_dict(), indent=2))
    else:
        q.print_table()
        print("\nAssumptions:", json.dumps(q.assumptions, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
