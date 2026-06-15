"""AI Ark healthcare CEO/founder/owner net-new search, preview, and export."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "healthcare-export"
LIST_IDS_PATH = ARTIFACTS / "list_ids.json"
API_EXCLUDE_PATH = ARTIFACTS / "api_exclude_lists.json"
OUT_CSV = ARTIFACTS / "Healthcare-founders-owners-netnew.csv"
OUT_CSV_5K = ARTIFACTS / "Healthcare-founders-owners-netnew-5000.csv"
PREVIEW_JSON = ARTIFACTS / "healthcare-founders-preview.json"

DEFAULT_EXPORT_LIMIT = 5000
TARGET_LIST_NAME = "healthcare - csuite"

API_BASE = "https://api.ai-ark.com/api/developer-portal"
LABEL = "Healthcare founders/owners netnew"

LIST_NAMES = {
    "healthcare - csuite": "healthcare - csuite",
    "healthcare - ops": "healthcare - ops",
}

LIST_ENV_KEYS = {
    "healthcare - csuite": "AIARK_LIST_CSUITE_UUID",
    "healthcare - ops": "AIARK_LIST_OPS_UUID",
}

APP_API_BASE = "https://app.ai-ark.com/api"

HEALTHCARE_INDUSTRIES = [
    "hospitals and health care",
    "medical practices",
    "mental health care",
    "medical equipment manufacturing",
    "pharmaceutical manufacturing",
    "biotechnology research",
    "wellness and fitness services",
    "alternative medicine",
    "individual and family services",
    "veterinary services",
]

TITLE_KEYWORDS = [
    "CEO",
    "Chief Executive Officer",
    "Founder",
    "Co-Founder",
    "Owner",
]

STANDARD_HEADERS = [
    "First Name",
    "Last Name",
    "Title",
    "Org",
    "Headline",
    "Summary",
    "Creator",
    "MX Records",
    "Email Business",
    "Business Status",
    "Domain Settings",
    "Mobile Phone",
    "Country",
    "State",
    "City",
    "Seniority",
    "Department",
    "LinkedIn",
    "Company Name",
    "Company Employee Count",
    "Company Size",
    "Company Industry",
    "Company Product and Services",
    "Company Description",
    "Company Website",
    "Company LinkedIn",
    "Company Type",
    "Company Number Of Locations",
    "Company Annual Revenue",
    "Company Total Funding",
    "Company Last Funding Type",
    "Domain",
    "Email Status",
    "Domain Type",
    "Label",
]


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def api_key() -> str:
    load_dotenv()
    key = os.environ.get("AIARK_API_KEY", "").strip()
    if not key:
        raise SystemExit("AIARK_API_KEY is not set (.env or environment).")
    return key


def api_request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "X-TOKEN": api_key(),
            "Content-Type": "application/json",
            "User-Agent": "curl/8.5.0",
        },
        method=method,
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"AI Ark API error {exc.code} on {path}: {detail}") from exc
    raise SystemExit(f"AI Ark API error 429 on {path} after retries")


def build_search_payload(list_uuids: list[str] | None = None) -> dict:
    payload: dict = {
        "account": {
            "location": {"any": {"include": ["United States"]}},
            "employeeSize": {
                "type": "RANGE",
                "range": [{"start": 5, "end": 500}],
            },
            "industries": {
                "any": {
                    "include": {
                        "mode": "WORD",
                        "content": HEALTHCARE_INDUSTRIES,
                    }
                }
            },
        },
        "contact": {
            "seniority": {
                "any": {"include": ["founder", "owner", "c_suite"]},
            },
            "experience": {
                "current": {
                    "title": {
                        "any": {
                            "include": {
                                "mode": "SMART",
                                "content": TITLE_KEYWORDS,
                            }
                        }
                    }
                }
            },
            "location": {"any": {"include": ["United States"]}},
        },
    }
    if list_uuids:
        payload["lists"] = {"people_id": {"exclude": list_uuids}}
    return payload


def load_list_ids() -> dict[str, str]:
    mapping: dict[str, str] = {}
    if LIST_IDS_PATH.exists():
        data = json.loads(LIST_IDS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            mapping = {str(k): str(v) for k, v in data.items() if v}
    for name, env_key in LIST_ENV_KEYS.items():
        val = os.environ.get(env_key, "").strip()
        if val and name not in mapping:
            mapping[name] = val
    return mapping


def workspace_id() -> str | None:
    cached = os.environ.get("AIARK_WORKSPACE_ID", "").strip()
    if cached:
        return cached
    try:
        result = api_request(
            "POST",
            "/v1/lists",
            {"type": "people_id", "values": ["00000123-c2fb-6d05-e5fc-a270045ca7d0"]},
        )
    except SystemExit:
        return None
    wid = result.get("workspace")
    return str(wid) if wid else None


def fetch_workspace_lists(wid: str) -> dict[str, str]:
    """Resolve list names via app bootstrap (requires OAuth; X-TOKEN usually 401)."""
    url = f"{APP_API_BASE}/elephant-management/um/workspaces/{wid}/bootstrap"
    req = urllib.request.Request(
        url,
        headers={
            "X-TOKEN": api_key(),
            "Content-Type": "application/json",
            "User-Agent": "curl/8.5.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return {}

    found: dict[str, str] = {}
    for key in ("lists", "searchLists", "search_lists"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("label")
            uuid = item.get("id")
            if name in LIST_NAMES and uuid:
                found[name] = str(uuid)
    return found


def load_api_exclude_list_ids() -> list[str]:
    if not API_EXCLUDE_PATH.exists():
        return []
    data = json.loads(API_EXCLUDE_PATH.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        ids = data.get("exclude_list_ids") or data.get("list_ids") or []
        return [str(x) for x in ids if x]
    if isinstance(data, list):
        return [str(x) for x in data if x]
    return []


def save_api_exclude_list_ids(list_ids: list[str], *, target_list: str) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    API_EXCLUDE_PATH.write_text(
        json.dumps(
            {
                "target_list_name": target_list,
                "exclude_list_ids": list_ids,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def all_exclude_list_uuids() -> list[str]:
    workspace = [v for v in resolve_list_ids(quiet=True) if v]
    api_lists = load_api_exclude_list_ids()
    seen: set[str] = set()
    merged: list[str] = []
    for uuid in workspace + api_lists:
        if uuid and uuid not in seen:
            seen.add(uuid)
            merged.append(uuid)
    return merged


def person_id(item: dict) -> str:
    return str(item.get("id") or "")


def append_people_to_api_list(people_ids: list[str], list_id: str | None = None) -> str:
    """Append AI Ark person IDs to a developer-portal exclude list (max 10k per list)."""
    if not people_ids:
        raise ValueError("No people IDs to append")

    remaining = people_ids[:]
    current_list_id = list_id
    updated_ids = load_api_exclude_list_ids()

    while remaining:
        batch = remaining[:10000]
        remaining = remaining[10000:]
        body: dict = {
            "type": "people_id",
            "values": batch,
            "mode": "APPEND",
        }
        if current_list_id:
            body["id"] = current_list_id
        result = api_request("POST", "/v1/lists", body)
        current_list_id = str(result["id"])
        if current_list_id not in updated_ids:
            updated_ids.append(current_list_id)

    save_api_exclude_list_ids(updated_ids, target_list=TARGET_LIST_NAME)
    return current_list_id or ""


def save_list_ids(mapping: dict[str, str]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    LIST_IDS_PATH.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_list_ids(*, quiet: bool = False) -> list[str]:
    mapping = load_list_ids()
    missing = [name for name in LIST_NAMES if name not in mapping or not mapping[name]]
    if not missing:
        return [mapping[name] for name in LIST_NAMES]

    wid = workspace_id()
    if wid:
        mapping.update({k: v for k, v in fetch_workspace_lists(wid).items() if v})

    # No documented list-by-name API on developer-portal; probe candidate endpoints.
    probes = [
        ("/v1/lists/find", {"names": list(LIST_NAMES.values())}),
        ("/v1/records/lists/search", {"names": list(LIST_NAMES.values())}),
    ]
    for path, body in probes:
        try:
            result = api_request("POST", path, body)
        except SystemExit:
            continue
        if isinstance(result, dict):
            for item in result.get("content") or result.get("lists") or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("label")
                uuid = item.get("id")
                if name in LIST_NAMES and uuid:
                    mapping[name] = uuid

    missing = [name for name in LIST_NAMES if name not in mapping or not mapping[name]]
    if missing and not quiet:
        print(
            "Could not resolve list UUIDs for: "
            + ", ".join(missing)
            + f"\nAdd them to {LIST_IDS_PATH} as JSON, e.g.\n"
            + json.dumps(
                {name: "<uuid-from-ai-ark-list-management>" for name in LIST_NAMES},
                indent=2,
            ),
            file=sys.stderr,
        )
    return []

    save_list_ids(mapping)
    return [mapping[name] for name in LIST_NAMES]


def people_search(page: int, size: int, list_uuids: list[str] | None) -> dict:
    payload = build_search_payload(list_uuids)
    payload["page"] = page
    payload["size"] = size
    return api_request("POST", "/v1/people", payload)


def norm_linkedin(url: str | None) -> str:
    if not url:
        return ""
    u = url.strip().lower().rstrip("/")
    return re.sub(r"\?.*$", "", u)


def staff_fields(staff: dict | None) -> tuple[str, str]:
    if not staff:
        return "", ""
    total = staff.get("total")
    rng = staff.get("range") or {}
    lo, hi = rng.get("start"), rng.get("end")
    if lo is not None and hi is not None:
        bucket = f"{lo}-{hi}"
    elif lo is not None:
        bucket = f"{lo}+"
    else:
        bucket = ""
    size = str(total) if total is not None else ""
    return bucket, size


def revenue_str(fin: dict | None) -> str:
    if not fin:
        return ""
    rev = (fin.get("revenue") or {}).get("annual") or {}
    return rev.get("amount") or ""


def funding_fields(fin: dict | None) -> tuple[str, str]:
    if not fin:
        return "", ""
    fund = fin.get("funding") or {}
    total = fund.get("total_amount")
    ftype = fund.get("type")
    return (str(total) if total is not None else ""), (ftype or "")


def _org_name(item: dict, csum: dict) -> str:
    groups = item.get("position_groups") or []
    if groups:
        company = groups[0].get("company") or {}
        name = company.get("name")
        if name:
            return name
    return csum.get("name") or ""


def company_key(item: dict) -> str:
    company = item.get("company") or {}
    csum = company.get("summary") or {}
    clink = company.get("link") or {}
    domain = clink.get("domain_ltd") or clink.get("domain") or ""
    if domain and "://" in domain:
        domain = re.sub(r"^https?://", "", domain).split("/")[0]
    if domain:
        return domain.lower()
    linkedin = clink.get("linkedin") or ""
    if linkedin:
        return norm_linkedin(linkedin)
    name = csum.get("name") or _org_name(item, csum)
    return name.lower()


def person_to_row(item: dict) -> dict[str, str]:
    profile = item.get("profile") or {}
    link = item.get("link") or {}
    loc = item.get("location") or {}
    dept = item.get("department") or {}
    company = item.get("company") or {}
    csum = company.get("summary") or {}
    clink = company.get("link") or {}
    cfin = company.get("financial") or {}
    cloc = company.get("location") or {}

    emp_count_bucket, emp_size = staff_fields(csum.get("staff"))
    rev = revenue_str(cfin)
    total_fund, last_fund = funding_fields(cfin)

    industries = csum.get("industries") or []
    if isinstance(industries, list):
        industry = ", ".join(industries) if industries else (csum.get("industry") or "")
    else:
        industry = csum.get("industry") or ""

    keywords = csum.get("keywords") or []
    products = ", ".join(keywords) if isinstance(keywords, list) else ""

    departments = dept.get("departments") or []
    dept_str = ", ".join(departments) if isinstance(departments, list) else ""

    domain = clink.get("domain_ltd") or clink.get("domain") or ""
    if domain and "://" in domain:
        domain = re.sub(r"^https?://", "", domain).split("/")[0]

    sub_orgs = csum.get("sub_organizations") or []
    num_locs = str(len(sub_orgs)) if sub_orgs else "0"

    badges = item.get("member_badges") or {}
    creator = "Yes" if badges.get("creator") else "No"

    return {
        "First Name": profile.get("first_name") or "",
        "Last Name": profile.get("last_name") or "",
        "Title": profile.get("title") or "",
        "Org": _org_name(item, csum),
        "Headline": profile.get("headline") or "",
        "Summary": profile.get("summary") or "",
        "Creator": creator,
        "MX Records": "",
        "Email Business": link.get("email") or item.get("email") or "",
        "Business Status": "",
        "Domain Settings": "",
        "Mobile Phone": link.get("phone") or "",
        "Country": loc.get("country") or (cloc.get("headquarter") or {}).get("country") or "",
        "State": loc.get("state") or (cloc.get("headquarter") or {}).get("state") or "",
        "City": loc.get("city") or (cloc.get("headquarter") or {}).get("city") or "",
        "Seniority": dept.get("seniority") or "",
        "Department": dept_str,
        "LinkedIn": link.get("linkedin") or "",
        "Company Name": csum.get("name") or "",
        "Company Employee Count": emp_count_bucket,
        "Company Size": emp_size,
        "Company Industry": industry,
        "Company Product and Services": products,
        "Company Description": csum.get("description") or "",
        "Company Website": clink.get("website") or clink.get("domain") or "",
        "Company LinkedIn": clink.get("linkedin") or "",
        "Company Type": csum.get("type") or "",
        "Company Number Of Locations": num_locs,
        "Company Annual Revenue": rev,
        "Company Total Funding": total_fund,
        "Company Last Funding Type": last_fund,
        "Domain": domain,
        "Email Status": "",
        "Domain Type": "",
        "Label": LABEL,
    }


def cap_per_company(items: list[dict], max_per_company: int = 2) -> list[dict]:
    counts: dict[str, int] = {}
    capped: list[dict] = []
    for item in items:
        key = company_key(item)
        if not key:
            capped.append(item)
            continue
        seen = counts.get(key, 0)
        if seen >= max_per_company:
            continue
        counts[key] = seen + 1
        capped.append(item)
    return capped


def filter_summary(list_uuids: list[str]) -> str:
    lines = [
        "Filters:",
        "  Titles (SMART): " + ", ".join(TITLE_KEYWORDS),
        "  Seniority: founder, owner, c_suite",
        "  Person location: United States",
        "  Company location: United States",
        "  Employee size: 5-500",
        "  Industries (WORD): " + "; ".join(HEALTHCARE_INDUSTRIES),
        "  Max per company (export): 2",
    ]
    mapping = load_list_ids()
    api_lists = load_api_exclude_list_ids()
    if mapping:
        lines.append("  Excluded workspace lists:")
        for name in LIST_NAMES:
            if mapping.get(name):
                lines.append(f"    - {name}: {mapping.get(name)}")
    if api_lists:
        lines.append(
            f"  Excluded API lists (prior exports -> {TARGET_LIST_NAME}): "
            + ", ".join(api_lists)
        )
    if not mapping and not api_lists:
        lines.append(
            "  Excluded lists: none (workspace UUIDs unavailable; "
            "using API exclude lists after first export)"
        )
    elif list_uuids:
        pass
    return "\n".join(lines)


def sample_line(item: dict, index: int) -> str:
    profile = item.get("profile") or {}
    company = item.get("company") or {}
    csum = company.get("summary") or {}
    loc = item.get("location") or {}
    staff = csum.get("staff") or {}
    rng = staff.get("range") or {}
    emp = ""
    if rng.get("start") is not None and rng.get("end") is not None:
        emp = f"{rng['start']}-{rng['end']}"
    name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    city_state = ", ".join(
        x for x in [loc.get("city"), loc.get("state")] if x
    )
    industries = csum.get("industries") or [csum.get("industry")]
    industry = ", ".join(i for i in industries if i)
    linkedin = (item.get("link") or {}).get("linkedin") or ""
    return (
        f"{index}. {name} | {profile.get('title', '')} | "
        f"{csum.get('name', '')} | employees {emp} | {industry} | "
        f"{city_state} | {linkedin}"
    )


def cmd_resolve_lists() -> int:
    ids = resolve_list_ids()
    if ids:
        print(f"Resolved {len(ids)} list UUIDs -> {LIST_IDS_PATH}")
        print(json.dumps(load_list_ids(), indent=2))
        return 0
    return 2


def cmd_preview() -> int:
    list_uuids = all_exclude_list_uuids()
    result = people_search(page=0, size=10, list_uuids=list_uuids or None)
    gross = int(result.get("totalElements") or 0)
    samples = result.get("content") or []

    # Estimate exportable count after 2-per-company cap on first page only.
    capped_samples = cap_per_company(samples, 2)

    preview = {
        "gross_total_elements": gross,
        "list_exclusions_applied": bool(list_uuids),
        "excluded_lists": load_list_ids() if list_uuids else {},
        "filters": {
            "titles": TITLE_KEYWORDS,
            "seniority": ["founder", "owner", "c_suite"],
            "person_location": "United States",
            "company_location": "United States",
            "employee_size": "5-500",
            "industries": HEALTHCARE_INDUSTRIES,
            "max_per_company": 2,
        },
        "sample_count": len(samples),
        "samples": [person_to_row(x) for x in samples],
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    PREVIEW_JSON.write_text(
        json.dumps(preview, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(filter_summary(list_uuids))
    print()
    if list_uuids:
        print(f"Gross net-new (API totalElements, lists excluded): {gross:,}")
    else:
        print(f"Gross matches (no list exclusions): {gross:,}")
        print(
            "Note: Workspace list UUIDs unavailable; export uses API exclude "
            f"lists for repeat runs (target: {TARGET_LIST_NAME})."
        )
    print(
        "Exportable count will be lower after the 2-per-company cap "
        "(full count computed during export)."
    )
    print()
    print("Sample leads (up to 10):")
    for i, item in enumerate(samples[:10], 1):
        print(sample_line(item, i))
    print()
    print(f"Preview saved to {PREVIEW_JSON}")
    return 0


def fetch_people(list_uuids: list[str] | None, limit: int | None) -> list[dict]:
    page = 0
    size = 100
    all_items: list[dict] = []
    seen_linkedin: set[str] = set()

    while True:
        result = people_search(page=page, size=size, list_uuids=list_uuids)
        content = result.get("content") or []
        for item in content:
            li = norm_linkedin((item.get("link") or {}).get("linkedin"))
            if li and li in seen_linkedin:
                continue
            if li:
                seen_linkedin.add(li)
            all_items.append(item)
            if limit and len(all_items) >= limit:
                return all_items[:limit]

        total_pages = int(result.get("totalPages") or 0)
        print(f"Fetched page {page + 1}/{total_pages} ({len(all_items)} unique leads)")
        if result.get("last") or page + 1 >= total_pages:
            break
        page += 1
        time.sleep(0.22)

    return all_items


def cmd_export(limit: int, out_csv: Path, add_to_list: bool) -> int:
    workspace_uuids = resolve_list_ids(quiet=True)
    list_uuids = all_exclude_list_uuids()
    if workspace_uuids:
        print(f"Excluding workspace lists: {', '.join(workspace_uuids)}")
    elif load_api_exclude_list_ids():
        print(
            f"Excluding {len(load_api_exclude_list_ids())} prior API list(s) "
            f"(proxy for {TARGET_LIST_NAME})"
        )
    else:
        print(
            "Workspace list UUIDs not found — exporting current net-new page "
            f"results, then saving IDs to API list for {TARGET_LIST_NAME}."
        )

    page = 0
    size = 100
    capped: list[dict] = []
    seen_linkedin: set[str] = set()
    raw_count = 0

    while len(capped) < limit:
        result = people_search(page=page, size=size, list_uuids=list_uuids or None)
        content = result.get("content") or []
        if not content:
            break
        batch: list[dict] = []
        for item in content:
            li = norm_linkedin((item.get("link") or {}).get("linkedin"))
            if li and li in seen_linkedin:
                continue
            if li:
                seen_linkedin.add(li)
            batch.append(item)
            raw_count += 1
        capped = cap_per_company(capped + batch, 2)[:limit]

        total_pages = int(result.get("totalPages") or 0)
        print(
            f"Fetched page {page + 1}/{total_pages} "
            f"({raw_count} raw, {len(capped)} exportable)"
        )
        if result.get("last") or page + 1 >= total_pages:
            break
        page += 1
        time.sleep(0.22)

    rows = [person_to_row(item) for item in capped]

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=STANDARD_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    list_id = ""
    if add_to_list:
        ids = [person_id(item) for item in capped if person_id(item)]
        existing = load_api_exclude_list_ids()
        seed = existing[0] if existing else None
        list_id = append_people_to_api_list(ids, list_id=seed)
        print(
            f"Appended {len(ids):,} person IDs to API exclude list {list_id} "
            f"(target workspace list: {TARGET_LIST_NAME})"
        )

    print(filter_summary(list_uuids))
    print()
    print(f"Fetched {raw_count:,} unique leads before 2-per-company cap")
    print(f"Exported after cap: {len(rows):,}")
    print(f"Wrote {out_csv}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve-lists", help="Resolve workspace list UUIDs by name")
    sub.add_parser("preview", help="Print net-new count and 10 sample leads")
    export_parser = sub.add_parser("export", help="Export net-new leads (max 2 per company)")
    export_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_EXPORT_LIMIT,
        help=f"Max rows to export after 2-per-company cap (default: {DEFAULT_EXPORT_LIMIT})",
    )
    export_parser.add_argument(
        "--output",
        type=Path,
        default=OUT_CSV_5K,
        help="Output CSV path",
    )
    export_parser.add_argument(
        "--no-add-to-list",
        action="store_true",
        help="Skip appending exported person IDs to API exclude list",
    )
    args = parser.parse_args()

    if args.command == "resolve-lists":
        return cmd_resolve_lists()
    if args.command == "preview":
        return cmd_preview()
    if args.command == "export":
        return cmd_export(
            limit=args.limit,
            out_csv=args.output,
            add_to_list=not args.no_add_to_list,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
