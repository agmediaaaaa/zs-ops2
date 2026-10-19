#!/usr/bin/env python3
"""Pull US industrial CEOs via treg (Leadsforge search + email find). No AI Ark."""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://treg.to"
TOKEN = json.loads(Path.home().joinpath(".treg/config.json").read_text())["token"]
OUT = Path(os.environ.get("OUT", "/workspace/artifacts/industrial-ceos-us-treg.csv"))
TARGET_EMAILS = int(os.environ.get("TARGET_EMAILS", "200"))
MIN_BALANCE_MICRO = int(os.environ.get("MIN_BALANCE_MICRO", "8000"))  # stop under ~$0.008
SEARCH_PAGE = 50
MAX_SEARCH = int(os.environ.get("MAX_SEARCH", "1200"))

INDUSTRIES = [
    "manufacturing",
    "machinery manufacturing",
    "textile manufacturing",
    "chemical manufacturing",
    "plastics manufacturing",
    "motor vehicle manufacturing",
    "semiconductor manufacturing",
    "defense and space manufacturing",
    "automation machinery manufacturing",
    "railroad equipment manufacturing",
    "industrial machinery manufacturing",
    "packaging and containers manufacturing",
    "paper and forest product manufacturing",
    "computers and electronics manufacturing",
    "glass, ceramics and concrete manufacturing",
    "appliances, electrical, and electronics manufacturing",
    "aviation and aerospace component manufacturing",
    "computer hardware manufacturing",
    "medical equipment manufacturing",
    "food and beverage manufacturing",
    "mining",
    "oil and gas",
    "wholesale",
    "wholesale import and export",
    "wholesale building materials",
    "warehousing and storage",
    "transportation, logistics, supply chain and storage",
    "construction",
    "utilities",
]

SEARCH_BODY = {
    "leadJobTitles": {
        "include": [
            "CEO",
            "Chief Executive Officer",
            "Owner",
            "President & CEO",
            "Founder & CEO",
            "President/CEO",
        ]
    },
    "companyLocations": {"include": ["United States"]},
    "leadLocations": {"include": ["United States"]},
    "companyEmployeeNumberRange": {"min": 20},
    "companyRevenueRanges": [
        "mid_sized_lower",
        "mid_sized_upper",
        "large_lower",
        "large_upper",
        "enterprise_lower",
        "enterprise_upper",
        "global_giants_lower",
        "global_giants_upper",
        "super_enterprises",
    ],
    "companyTypes": {"include": ["PRIVATELY_HELD", "PARTNERSHIP", "SELF_OWNED"]},
    "companyFundingRounds": {
        "exclude": [
            "PRIVATE_EQUITY",
            "SEED",
            "SERIES_A",
            "SERIES_B",
            "SERIES_C",
            "SERIES_D",
            "SERIES_E",
            "SERIES_F",
            "SERIES_G",
            "SERIES_H",
            "SERIES_I",
            "VENTURE_SERIES_UNKNOWN",
            "ANGEL",
            "PRE_SEED",
            "CONVERTIBLE_NOTE",
            "EQUITY_CROWDFUNDING",
            "INITIAL_COIN_OFFERING",
        ]
    },
    "companyIndustries": {"include": INDUSTRIES},
    "companyRequired": True,
    "maxContactsPerCompany": 1,
    "limit": SEARCH_PAGE,
}

COLUMNS = [
    "First Name",
    "Last Name",
    "Full Name",
    "Title",
    "Organization",
    "MX Records",
    "Email Provider",
    "Email Business",
    "Business Status",
    "Domain Settings",
    "Mobile Phone",
    "Location",
    "Country",
    "State",
    "City",
    "Seniority",
    "Department",
    "LinkedIn",
    "LinkedIn Followers",
    "Last Updated",
    "AI Ark People ID",
    "Company Name",
    "Company Name for Emails",
    "Company Employee Count",
    "Company Size",
    "Company Total headcount growth (3 months)",
    "Company Total headcount growth (6 months)",
    "Company Total headcount growth (12 months)",
    "Company Total headcount growth (24 months)",
    "Company Industry",
    "Company Industry Tags",
    "Company NAICS Code",
    "Company Product and Services",
    "Company Description",
    "Company SEO Description",
    "Company Website",
    "Company LinkedIn",
    "Company LinkedIn Followers",
    "Company X (Twitter)",
    "Company Facebook",
    "Company Instagram",
    "Company Type",
    "Company Number Of Locations",
    "Company Location",
    "Company Country",
    "Company State",
    "Company City",
    "Company Primary Phone",
    "Company Founding Year",
    "Company Annual Revenue",
    "Company Total Funding",
    "Company Last Funding Type",
    "Company Last Funding Amount",
    "Company Last Funding Date",
    "Company Technologies",
    "Company AI Ark account ID",
    "Company Last Updated",
    "Source Person ID",
    "Source Company ID",
    "Email Provider Used",
    "Email Cost USD",
]


def treg(method: str, path: str, body=None, headers=None, retries=4):
    url = f"{BASE}{path}"
    data = None if body is None else json.dumps(body).encode()
    hdrs = {
        "X-Treg-Token": TOKEN,
        "Accept": "application/json",
    }
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    last = None
    for i in range(retries):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
                meta = {
                    "status": resp.status,
                    "call_id": resp.headers.get("X-Treg-Call-Id"),
                    "cost_micro": int(resp.headers.get("X-Treg-Cost-Micro") or 0),
                    "served_by": resp.headers.get("X-Treg-Served-By"),
                }
                if not raw:
                    return None, meta
                return json.loads(raw.decode()), meta
        except urllib.error.HTTPError as e:
            err = e.read().decode(errors="replace")
            last = (e.code, err)
            if e.code == 410:
                return {"_gone": True, "detail": err}, {
                    "status": 410,
                    "call_id": e.headers.get("X-Treg-Call-Id") if e.headers else None,
                    "cost_micro": 0,
                    "served_by": None,
                }
            if e.code in (409, 429, 503) or (500 <= e.code < 600):
                time.sleep(min(2 ** i, 16))
                continue
            raise RuntimeError(f"HTTP {e.code}: {err[:800]}") from e
        except Exception as e:
            last = e
            time.sleep(min(2 ** i, 8))
    raise RuntimeError(f"failed after retries: {last}")


def balance_micro() -> int:
    import subprocess

    out = subprocess.check_output(["treg", "balance"], text=True)
    for line in out.splitlines():
        if "Balance" in line and "$" in line:
            amt = line.split("$", 1)[1].split()[0].replace(",", "")
            return int(round(float(amt) * 1_000_000))
    raise RuntimeError(f"could not parse balance:\n{out}")


def fmt_loc(parts):
    return ", ".join(p for p in parts if p)


def revenue_bucket(rr):
    if not rr:
        return ""
    start = rr.get("start")
    end = rr.get("end")
    if start is None and end is None:
        return ""
    if end is None:
        return f"{start}+"
    return f"{start}-{end}"


def row_from(lead, email="", email_meta=None):
    loc = lead.get("location") or {}
    co = lead.get("company") or {}
    cloc = co.get("location") or {}
    bits = (email_meta or {}).get("enrich_bits") or {}
    first = (lead.get("firstName") or "").strip()
    last = (lead.get("lastName") or "").strip()
    keywords = co.get("keywords") or []
    if isinstance(keywords, list):
        tags = ", ".join(str(k) for k in keywords)
    else:
        tags = str(keywords or "")
    years = co.get("yearsInBusiness")
    founding = ""
    if isinstance(years, int) and years >= 0:
        founding = str(time.gmtime().tm_year - years)
    emp = co.get("employeeCount")
    domain = (co.get("domain") or "").strip()
    website = (co.get("website") or domain or "").strip()
    website = website.replace("https://", "").replace("http://", "").rstrip("/")
    company_name = (co.get("name") or bits.get("company_name") or domain or "").strip()
    email_meta = email_meta or {}
    city = loc.get("city") or bits.get("city") or ""
    state = loc.get("state") or bits.get("state") or ""
    country = loc.get("country") or "United States"
    c_city = cloc.get("city") or bits.get("city") or ""
    c_state = cloc.get("state") or bits.get("state") or ""
    c_country = cloc.get("country") or "United States"
    return {
        "First Name": first,
        "Last Name": last,
        "Full Name": f"{first} {last}".strip(),
        "Title": lead.get("jobTitle") or "",
        "Organization": company_name,
        "MX Records": "",
        "Email Provider": "",
        "Email Business": email or "",
        "Business Status": "found" if email else "",
        "Domain Settings": "",
        "Mobile Phone": "",
        "Location": fmt_loc([city, state, country]),
        "Country": country,
        "State": state,
        "City": city,
        "Seniority": "c_suite",
        "Department": "general_management",
        "LinkedIn": lead.get("linkedinUrl")
        or lead.get("linkedin")
        or bits.get("linkedin")
        or "",
        "LinkedIn Followers": "",
        "Last Updated": "",
        "AI Ark People ID": "",
        "Company Name": company_name,
        "Company Name for Emails": company_name,
        "Company Employee Count": emp if emp is not None else "",
        "Company Size": emp if emp is not None else "",
        "Company Total headcount growth (3 months)": "",
        "Company Total headcount growth (6 months)": "",
        "Company Total headcount growth (12 months)": "",
        "Company Total headcount growth (24 months)": "",
        "Company Industry": co.get("industry") or bits.get("industry") or "",
        "Company Industry Tags": tags,
        "Company NAICS Code": "",
        "Company Product and Services": tags,
        "Company Description": co.get("description") or "",
        "Company SEO Description": "",
        "Company Website": website,
        "Company LinkedIn": co.get("linkedinUrl") or bits.get("company_linkedin") or "",
        "Company LinkedIn Followers": "",
        "Company X (Twitter)": "",
        "Company Facebook": "",
        "Company Instagram": "",
        "Company Type": "PRIVATELY_HELD/PARTNERSHIP/SELF_OWNED",
        "Company Number Of Locations": co.get("numberOfLocations")
        or co.get("locationsCount")
        or "",
        "Company Location": fmt_loc(
            [bits.get("address"), c_city, c_state, c_country]
        ),
        "Company Country": c_country,
        "Company State": c_state,
        "Company City": c_city,
        "Company Primary Phone": co.get("phone") or bits.get("company_phone") or "",
        "Company Founding Year": founding,
        "Company Annual Revenue": revenue_bucket(co.get("revenueRange")),
        "Company Total Funding": "",
        "Company Last Funding Type": "",
        "Company Last Funding Amount": "",
        "Company Last Funding Date": "",
        "Company Technologies": "",
        "Company AI Ark account ID": "",
        "Company Last Updated": "",
        "Source Person ID": lead.get("id") or "",
        "Source Company ID": co.get("id") or "",
        "Email Provider Used": email_meta.get("served_by") or "",
        "Email Cost USD": f"{(email_meta.get('cost_micro') or 0) / 1_000_000:.6f}",
    }


def search_page(cursor=None):
    body = dict(SEARCH_BODY)
    path = "/call/leadsforge.people.search"
    if cursor:
        path += f"?cursor={urllib.request.quote(cursor)}"
    data, meta = treg("POST", path, body)
    return data or {}, meta


def find_email(lead):
    co = lead.get("company") or {}
    domain = (co.get("domain") or "").strip()
    first = (lead.get("firstName") or "").strip()
    last = (lead.get("lastName") or "").strip()
    if not domain or not first or not last:
        return "", {"cost_micro": 0, "served_by": ""}
    body = {
        "domain": domain,
        "first_name": first,
        "last_name": last,
        "full_name": f"{first} {last}",
    }
    headers = {
        "X-Treg-Route-Exclude": "aiark",
        # Stay on cheapest providers (~$0.0048–$0.005) to maximize emails per $1.
        "X-Treg-Route-Max-Cost": "0.006",
        "X-Treg-Route-Waterfall": "0",
        "Idempotency-Key": f"ceo-email-{lead.get('id')}",
    }
    data, meta = treg("POST", "/call/treg.people.email.find", body, headers=headers)
    email = ""
    enrich_bits = {}
    if isinstance(data, dict):
        out = data.get("output") or data
        if isinstance(out, dict):
            email = out.get("email") or out.get("work_email") or out.get("value") or ""
            if not email and isinstance(out.get("emails"), list) and out["emails"]:
                e0 = out["emails"][0]
                email = e0 if isinstance(e0, str) else (e0.get("email") or "")
        raw = data.get("raw")
        if isinstance(raw, dict):
            raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            if not email:
                email = raw_data.get("email") or raw_data.get("work_email") or ""
            for src_key, dst_key in (
                ("employee_linkedin", "linkedin"),
                ("company_name", "company_name"),
                ("company_linked", "company_linkedin"),
                ("company_phone", "company_phone"),
                ("industry", "industry"),
                ("address", "address"),
                ("city", "city"),
                ("region_code", "state"),
            ):
                if raw_data.get(src_key):
                    enrich_bits[dst_key] = raw_data[src_key]
    meta = dict(meta or {})
    meta["enrich_bits"] = enrich_bits
    return (email or "").strip(), meta


def load_existing():
    rows = []
    seen_people = set()
    seen_domains = set()
    seen_emails = set()
    if not OUT.exists():
        return rows, seen_people, seen_domains, seen_emails
    with OUT.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
            if r.get("Source Person ID"):
                seen_people.add(r["Source Person ID"])
            site = (r.get("Company Website") or "").lower().strip()
            if site:
                seen_domains.add(site)
            em = (r.get("Email Business") or "").lower().strip()
            if em:
                seen_emails.add(em)
    return rows, seen_people, seen_domains, seen_emails


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    start_bal = balance_micro()
    print(f"start_balance_usd={start_bal/1_000_000:.4f}", flush=True)

    rows, seen_people, seen_domains, seen_emails = load_existing()
    hits = len(rows)
    print(f"resuming existing_rows={hits}", flush=True)

    leads = []
    cursor = None
    # Shard by industry so we stay under Leadsforge's ~1000-result search cap.
    industry_shards = [INDUSTRIES[i : i + 4] for i in range(0, len(INDUSTRIES), 4)]
    for shard_i, shard in enumerate(industry_shards):
        if len(leads) >= MAX_SEARCH:
            break
        cursor = None
        print(f"shard={shard_i+1}/{len(industry_shards)} industries={shard}", flush=True)
        while len(leads) < MAX_SEARCH:
            body = dict(SEARCH_BODY)
            body["companyIndustries"] = {"include": shard}
            path = "/call/leadsforge.people.search"
            if cursor:
                path += f"?cursor={urllib.request.quote(cursor)}"
            data, meta = treg("POST", path, body)
            if data.get("_gone"):
                print(f"shard={shard_i+1} hit provider cap; next shard", flush=True)
                break
            batch = data.get("leads") or []
            if not batch:
                print(f"shard={shard_i+1} exhausted", flush=True)
                break
            for lead in batch:
                pid = lead.get("id")
                domain = ((lead.get("company") or {}).get("domain") or "").lower()
                if not pid or pid in seen_people:
                    continue
                if domain and domain in seen_domains:
                    continue
                seen_people.add(pid)
                if domain:
                    seen_domains.add(domain)
                leads.append(lead)
            cursor = data.get("cursor")
            print(f"searched={len(leads)} cursor={'yes' if cursor else 'no'}", flush=True)
            if not cursor:
                break
            time.sleep(0.05)

    print(f"candidates={len(leads)}", flush=True)

    spent = 0
    tries = 0
    for lead in leads:
        if hits >= TARGET_EMAILS:
            break
        bal = balance_micro()
        if bal < MIN_BALANCE_MICRO:
            print(f"stop: balance_usd={bal/1_000_000:.4f}", flush=True)
            break
        tries += 1
        try:
            email, meta = find_email(lead)
        except Exception as e:
            print(f"email_err {lead.get('id')}: {e}", flush=True)
            time.sleep(0.5)
            continue
        cost = int(meta.get("cost_micro") or 0)
        spent += cost
        if email:
            em = email.lower()
            if em in seen_emails:
                continue
            seen_emails.add(em)
            hits += 1
            rows.append(row_from(lead, email, meta))
            if hits % 10 == 0 or hits <= 5:
                print(
                    f"hits={hits} tries={tries} spent_usd={spent/1_000_000:.4f} "
                    f"bal={balance_micro()/1_000_000:.4f} last={email}",
                    flush=True,
                )
                with OUT.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
        else:
            if tries % 25 == 0:
                print(
                    f"misses tries={tries} hits={hits} spent_usd={spent/1_000_000:.4f} "
                    f"bal={balance_micro()/1_000_000:.4f}",
                    flush=True,
                )
        time.sleep(0.03)

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    end_bal = balance_micro()
    summary = {
        "out": str(OUT),
        "rows_with_email": len(rows),
        "email_tries": tries,
        "candidates": len(leads),
        "spent_usd": round(spent / 1_000_000, 6),
        "start_balance_usd": round(start_bal / 1_000_000, 4),
        "end_balance_usd": round(end_bal / 1_000_000, 4),
        "providers": "treg.people.email.find (exclude aiark); leadsforge.people.search",
    }
    Path(str(OUT) + ".summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
