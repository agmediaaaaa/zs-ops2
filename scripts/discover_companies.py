#!/usr/bin/env python3
"""Parallel company/people discovery via Treg with catalog-priced quotes.

Flow:
  1. Free count (icypeas.*.search.count)
  2. Catalog quote (scripts/treg_pricing.py)
  3. --confirm-spend hard gate
  4. Parallel page fetch (AI Ark page numbers) or sharded Icypeas streams
  5. Dedupe on domain / LinkedIn; write JSON/CSV

Examples:
  # Scope only (free)
  python scripts/discover_companies.py --industry "Software Development" \\
      --headcount-min 11 --headcount-max 50 --target 5000 --scope-only

  # Paid discovery after quote
  python scripts/discover_companies.py --industry "Software Development" \\
      --headcount-min 11 --headcount-max 50 --target 500 \\
      --provider aiark --confirm-spend 1.00
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import treg_pricing

BASE = "https://treg.to"
OUT_DIR = Path(os.environ.get("OUT_DIR", "/workspace/artifacts/discover"))
USER_AGENT = "zs-ops2-discover/1.0"

_spend_lock = threading.Lock()
_spent_micro = 0
_cap_micro = 0
_stop = False
TOKEN = ""


def load_treg_token() -> str:
    for name in ("TREG_TOKEN", "treg"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    cfg = Path.home() / ".treg" / "config.json"
    if cfg.exists():
        data = json.loads(cfg.read_text())
        tok = data.get("token") or data.get("TREG_TOKEN") or ""
        if tok:
            return tok
    raise SystemExit("Set TREG_TOKEN or run scripts/setup-treg.sh")


def treg(
    method: str,
    path: str,
    body: Any | None = None,
    query: dict | None = None,
    retries: int = 3,
    timeout: float = 60,
) -> tuple[Any, dict]:
    url = f"{BASE}{path}"
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    data = None if body is None else json.dumps(body).encode()
    hdrs = {
        "X-Treg-Token": TOKEN,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    last: Any = None
    for i in range(retries):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                meta = {
                    "status": resp.status,
                    "call_id": resp.headers.get("X-Treg-Call-Id"),
                    "cost_micro": int(resp.headers.get("X-Treg-Cost-Micro") or 0),
                    "served_by": resp.headers.get("X-Treg-Served-By"),
                }
                charge(int(meta["cost_micro"]))
                if not raw:
                    return None, meta
                return json.loads(raw.decode()), meta
        except urllib.error.HTTPError as e:
            err = e.read().decode(errors="replace")
            last = (e.code, err)
            if e.code in (409, 418, 429, 503) or (500 <= e.code < 600):
                wait = min(2 * (2**i), 20)
                if e.code in (418, 429):
                    wait = max(wait, 4 + 3 * i)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {err[:800]}") from e
        except Exception as e:
            last = e
            time.sleep(min(1.5**i, 4))
    raise RuntimeError(f"treg failed after retries: {last}")


def charge(cost_micro: int) -> None:
    global _spent_micro, _stop
    if cost_micro <= 0:
        return
    with _spend_lock:
        _spent_micro += cost_micro
        if _spent_micro >= _cap_micro > 0:
            _stop = True


def spent_usd() -> float:
    with _spend_lock:
        return _spent_micro / 1_000_000


def under_cap() -> bool:
    with _spend_lock:
        if _stop:
            return False
        if _cap_micro <= 0:
            return True
        return _spent_micro < _cap_micro


def normalize_domain(raw: str | None) -> str:
    if not raw:
        return ""
    d = raw.strip().lower()
    d = d.replace("https://", "").replace("http://", "")
    d = d.split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def icypeas_company_query(
    industry: str | None,
    keywords: list[str],
    headcount_min: int | None,
    headcount_max: int | None,
    location: str | None,
) -> dict[str, Any]:
    q: dict[str, Any] = {}
    if industry:
        q["industry"] = {"include": [industry]}
    if keywords:
        q["keyword"] = {"include": keywords}
    if headcount_min is not None or headcount_max is not None:
        hc: dict[str, Any] = {}
        if headcount_min is not None:
            hc[">="] = headcount_min
        if headcount_max is not None:
            hc["<="] = headcount_max
        q["headcount"] = hc
    if location:
        q["location"] = {"include": [location]}
    return q


def free_company_count(query: dict[str, Any]) -> int:
    data, _ = treg(
        "POST",
        "/call/icypeas.companies.search.count",
        {"query": query},
    )
    if isinstance(data, dict):
        return int(data.get("total") or data.get("count") or 0)
    return 0


def free_people_count(query: dict[str, Any]) -> int:
    data, _ = treg(
        "POST",
        "/call/icypeas.people.search.count",
        {"query": query},
    )
    if isinstance(data, dict):
        return int(data.get("total") or data.get("count") or 0)
    return 0


def extract_company_rows(data: Any) -> list[dict[str, Any]]:
    """Normalize provider payloads into {name, domain, linkedin, raw}."""
    rows: list[dict[str, Any]] = []
    if data is None:
        return rows
    items: list[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("companies", "results", "data", "items", "accounts", "hits"):
            val = data.get(key)
            if isinstance(val, list):
                items = val
                break
        if not items and "name" in data:
            items = [data]
    for item in items:
        if not isinstance(item, dict):
            continue
        # Nested account wrappers (AI Ark style)
        account = item.get("account") if isinstance(item.get("account"), dict) else item
        name = (
            account.get("name")
            or account.get("company_name")
            or account.get("companyName")
            or item.get("name")
            or ""
        )
        domain = normalize_domain(
            account.get("domain")
            or account.get("website")
            or account.get("company_domain")
            or item.get("domain")
            or item.get("website")
        )
        linkedin = (
            account.get("linkedin_url")
            or account.get("linkedin")
            or account.get("profileUrl")
            or item.get("linkedin")
            or ""
        )
        if isinstance(linkedin, str):
            linkedin = linkedin.strip()
        else:
            linkedin = ""
        if not name and not domain:
            continue
        rows.append(
            {
                "name": str(name).strip(),
                "domain": domain,
                "linkedin": linkedin,
                "raw": item,
            }
        )
    return rows


def icypeas_search_page(
    query: dict[str, Any],
    token: str | None,
    size: int = 100,
) -> tuple[list[dict], str | None, dict]:
    body: dict[str, Any] = {
        "query": query,
        "pagination": {"size": size},
    }
    if token:
        body["pagination"]["token"] = token
    data, meta = treg("POST", "/call/icypeas.companies.search", body)
    rows = extract_company_rows(data)
    nxt = None
    if isinstance(data, dict):
        nxt = ((data.get("pagination") or {}).get("token")) or None
    return rows, nxt, meta


def aiark_search_page(
    industry: str | None,
    keywords: list[str],
    headcount_min: int | None,
    headcount_max: int | None,
    page: int,
    size: int,
) -> tuple[list[dict], dict]:
    """AI Ark company search by page number (parallelizable)."""
    account: dict[str, Any] = {}
    if industry:
        account["industry"] = {"any": {"include": [industry]}}
    if keywords:
        # AI Ark keyword / description filters vary; put into free-text when present
        account["keywords"] = {"any": {"include": keywords}}
    if headcount_min is not None or headcount_max is not None:
        rng: dict[str, Any] = {}
        if headcount_min is not None:
            rng["min"] = headcount_min
        if headcount_max is not None:
            rng["max"] = headcount_max
        account["employees"] = rng
    body = {"account": account, "page": page, "size": size}
    data, meta = treg("POST", "/call/aiark.companies.search", body)
    return extract_company_rows(data), meta


def discover_icypeas_sharded(
    base_query: dict[str, Any],
    target: int,
    page_size: int,
    workers: int,
    shards: list[dict[str, Any]],
) -> tuple[list[dict], dict]:
    """Run multiple Icypeas token streams in parallel (one per shard filter)."""
    results: list[dict] = []
    seen: set[str] = set()
    lock = threading.Lock()
    stats = {"pages": 0, "shards": len(shards), "cost_micro": 0}

    def run_shard(shard_q: dict[str, Any]) -> None:
        nonlocal results
        token = None
        while under_cap():
            with lock:
                if len(results) >= target:
                    return
            rows, token, meta = icypeas_search_page(shard_q, token, size=page_size)
            with lock:
                stats["pages"] += 1
                stats["cost_micro"] += int(meta.get("cost_micro") or 0)
                for row in rows:
                    key = row["domain"] or row["linkedin"] or row["name"].lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    results.append(row)
                    if len(results) >= target:
                        return
            if not token or not rows:
                return

    # If no meaningful shards, single stream
    if not shards:
        shards = [base_query]

    with ThreadPoolExecutor(max_workers=min(workers, len(shards))) as pool:
        futs = [pool.submit(run_shard, {**base_query, **s}) for s in shards]
        for fut in as_completed(futs):
            fut.result()
            if not under_cap():
                break
    return results[:target], stats


def discover_aiark_parallel(
    industry: str | None,
    keywords: list[str],
    headcount_min: int | None,
    headcount_max: int | None,
    target: int,
    page_size: int,
    workers: int,
) -> tuple[list[dict], dict]:
    """True parallel page fetch using AI Ark page indices."""
    n_pages = max(1, (target + page_size - 1) // page_size)
    results: list[dict] = []
    seen: set[str] = set()
    lock = threading.Lock()
    stats = {"pages": 0, "planned_pages": n_pages, "cost_micro": 0}

    def fetch_page(page: int) -> None:
        nonlocal results
        if not under_cap():
            return
        rows, meta = aiark_search_page(
            industry, keywords, headcount_min, headcount_max, page, page_size
        )
        with lock:
            stats["pages"] += 1
            stats["cost_micro"] += int(meta.get("cost_micro") or 0)
            for row in rows:
                key = row["domain"] or row["linkedin"] or row["name"].lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                results.append(row)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(fetch_page, p) for p in range(n_pages)]
        for fut in as_completed(futs):
            fut.result()
            with lock:
                if len(results) >= target or not under_cap():
                    break
    return results[:target], stats


def default_location_shards(location: str | None) -> list[dict[str, Any]]:
    """Split US discovery into region shards for parallel Icypeas streams."""
    if location and location.lower() not in ("united states", "us", "usa"):
        return [{"location": {"include": [location]}}]
    regions = [
        "California",
        "Texas",
        "New York",
        "Florida",
        "Illinois",
        "Pennsylvania",
        "Ohio",
        "Georgia",
        "North Carolina",
        "Michigan",
        "New Jersey",
        "Virginia",
        "Washington",
        "Arizona",
        "Massachusetts",
        "Tennessee",
    ]
    return [{"location": {"include": [r]}} for r in regions]


def write_output(rows: list[dict], out_path: Path, fmt: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        slim = [
            {"name": r["name"], "domain": r["domain"], "linkedin": r["linkedin"]}
            for r in rows
        ]
        out_path.write_text(json.dumps(slim, indent=2))
    else:
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["name", "domain", "linkedin"])
            w.writeheader()
            for r in rows:
                w.writerow(
                    {
                        "name": r["name"],
                        "domain": r["domain"],
                        "linkedin": r["linkedin"],
                    }
                )


def main(argv: list[str] | None = None) -> int:
    global TOKEN, _cap_micro, _spent_micro, _stop

    p = argparse.ArgumentParser(description="Parallel Treg company discovery")
    p.add_argument("--industry", default=None)
    p.add_argument("--keyword", action="append", default=[])
    p.add_argument("--headcount-min", type=int, default=None)
    p.add_argument("--headcount-max", type=int, default=None)
    p.add_argument("--location", default="United States")
    p.add_argument("--target", type=int, default=500)
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument(
        "--provider",
        choices=["icypeas", "aiark"],
        default="aiark",
        help="aiark = parallel page numbers (default); icypeas = sharded token streams",
    )
    p.add_argument("--scope-only", action="store_true", help="Free count + quote only")
    p.add_argument("--confirm-spend", type=float, default=None)
    p.add_argument("--refresh-prices", action="store_true")
    p.add_argument("--format", choices=["csv", "json"], default="csv")
    p.add_argument(
        "--output",
        default=None,
        help="Output path (default artifacts/discover/companies.<fmt>)",
    )
    p.add_argument("--dry-run-quote", action="store_true", help="Quote without Treg token")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.dry_run_quote:
        company_ep = (
            "aiark.companies.search"
            if args.provider == "aiark"
            else "icypeas.companies.search"
        )
        q = treg_pricing.quote_run(
            mode="discover",
            companies=args.target,
            company_endpoint=company_ep,
            page_size=args.page_size,
            force_refresh=args.refresh_prices,
        )
        q.print_table()
        print(json.dumps(q.to_dict(), indent=2))
        return 0

    TOKEN = load_treg_token()

    query = icypeas_company_query(
        args.industry,
        args.keyword,
        args.headcount_min,
        args.headcount_max,
        args.location,
    )
    print(f"Query: {json.dumps(query)}", flush=True)

    t0 = time.time()
    tam = free_company_count(query)
    print(f"Free count (icypeas): {tam}", flush=True)

    pull = min(args.target, tam) if tam > 0 else args.target
    company_ep = (
        "aiark.companies.search"
        if args.provider == "aiark"
        else "icypeas.companies.search"
    )
    quote = treg_pricing.quote_run(
        mode="discover",
        companies=pull,
        company_endpoint=company_ep,
        page_size=args.page_size,
        force_refresh=args.refresh_prices,
    )
    quote.print_table()

    report = {
        "tam": tam,
        "target": args.target,
        "pull": pull,
        "provider": args.provider,
        "quote": quote.to_dict(),
        "query": query,
    }

    if args.scope_only:
        (OUT_DIR / "scope.json").write_text(json.dumps(report, indent=2))
        print(f"\nScope written to {OUT_DIR / 'scope.json'}")
        return 0

    if args.confirm_spend is None:
        print(
            "\nError: paid discovery requires --confirm-spend <usd> "
            f"(recommended >= {quote.recommended_cap_usd})",
            file=sys.stderr,
        )
        return 2

    if args.confirm_spend + 1e-9 < quote.expected_usd:
        print(
            f"\nError: --confirm-spend {args.confirm_spend} below expected "
            f"${quote.expected_usd:.4f}",
            file=sys.stderr,
        )
        return 2

    _cap_micro = int(args.confirm_spend * 1_000_000)
    _spent_micro = 0
    _stop = False

    print(
        f"\nDiscovering up to {pull} via {args.provider} "
        f"(workers={args.workers}, page_size={args.page_size})...",
        flush=True,
    )

    if args.provider == "aiark":
        rows, stats = discover_aiark_parallel(
            args.industry,
            args.keyword,
            args.headcount_min,
            args.headcount_max,
            pull,
            args.page_size,
            args.workers,
        )
    else:
        shards = default_location_shards(args.location)
        # Avoid double-applying location when sharding US states
        base = dict(query)
        if "location" in base and len(shards) > 1:
            base.pop("location", None)
        rows, stats = discover_icypeas_sharded(
            base, pull, args.page_size, args.workers, shards
        )

    elapsed = time.time() - t0
    actual = spent_usd()
    out = Path(
        args.output
        or str(OUT_DIR / f"companies.{args.format}")
    )
    write_output(rows, out, args.format)

    summary = {
        **report,
        "found": len(rows),
        "stats": stats,
        "actual_cost_usd": round(actual, 6),
        "quoted_expected_usd": quote.expected_usd,
        "quoted_max_usd": quote.max_usd,
        "variance_usd": round(actual - quote.expected_usd, 6),
        "elapsed_s": round(elapsed, 2),
        "output": str(out),
    }
    (OUT_DIR / "run_report.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {len(rows)} companies → {out}")
    print(
        f"Cost: actual ${actual:.4f} vs expected ${quote.expected_usd:.4f} "
        f"(cap ${args.confirm_spend:.2f}) in {elapsed:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
