#!/usr/bin/env python3
"""Plain-English interactive scrape wizard (safe Treg Icypeas → Blitz).

For non-technical use. It will:
  1. Ask who you want to target
  2. Ask ready-leads vs Icypeas-pull
  3. Show free TAM (after domain excludes)
  4. Show a cost estimate
  5. Ask YOU for the dollar cost cap
  6. Only then run paid Icypeas → Blitz

It will NEVER invent a cost cap or switch to another provider mid-run.

Usage:
  python scripts/scrape_wizard.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "treg_icypeas_blitz.py"
EXCLUDE_BUILDER = ROOT / "scripts" / "build_exclude_seed.py"
OUT_DIR = Path("/workspace/artifacts/scrape-wizard")
CONFIG_PATH = OUT_DIR / "last-run-config.json"
EXCLUDE_PATH = OUT_DIR / "exclude-seed.json"
DEFAULT_PLUSVIBE_WS = "6a8d53c5977bb5537e41fcf2"

DEFAULT_TITLES = "CEO|Founder|Owner|President|Co-Founder"
DEFAULT_TITLE_EXCLUDE = (
    "VP|Vice President|Assistant|Sales|Marketing|HR|Intern|Student|"
    "Retired|Former|Consultant|Advisor|Board Member"
)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        print("  Please type an answer.")


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    raw = input(f"{prompt} ({d}): ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def ask_float(prompt: str) -> float:
    while True:
        raw = input(f"{prompt}: ").strip().replace("$", "")
        try:
            v = float(raw)
            if v <= 0:
                print("  Enter a number greater than 0.")
                continue
            return v
        except ValueError:
            print("  Enter a number like 2.50")


def ask_int(prompt: str, default: int | None = None) -> int:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            v = int(raw)
            if v <= 0:
                print("  Enter a whole number greater than 0.")
                continue
            return v
        except ValueError:
            print("  Enter a whole number like 100")


def split_pipe_or_comma(raw: str) -> list[str]:
    if "|" in raw:
        parts = raw.split("|")
    else:
        parts = raw.split(",")
    return [p.strip() for p in parts if p.strip()]


def run_cmd(args: list[str]) -> int:
    print("\n--- running ---")
    print(" ", " ".join(args))
    print("---------------\n")
    return subprocess.call(args)


def main() -> None:
    print(
        """
========================================================
  SAFE LEAD SCRAPE WIZARD  (Icypeas → Blitz only)
========================================================
This tool will NOT spend money until YOU type a dollar cap.

Chat agents can invent steps. This script cannot change
path mid-run. It only does: Icypeas people search → Blitz.
========================================================
"""
    )
    if not RUNNER.exists():
        print(f"Missing runner: {RUNNER}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    client = ask("Client code (e.g. ATC, MARS, GWS, ZS)", "ZS")
    print(
        "\nTitles to INCLUDE (who you want).\n"
        "  Tip: separate with commas. Example: CEO, Founder, Owner, President"
    )
    titles = split_pipe_or_comma(ask("Titles include", DEFAULT_TITLES.replace("|", ", ")))

    print(
        "\nTitles to EXCLUDE (put in Icypeas query so you don't pay for junk)."
    )
    title_excl = split_pipe_or_comma(
        ask("Titles exclude", DEFAULT_TITLE_EXCLUDE.replace("|", ", "))
    )

    geo = split_pipe_or_comma(ask("Location / geo", "US"))
    hc_min = ask_int("Company headcount minimum", 5)
    hc_max = ask_int("Company headcount maximum", 100)

    print(
        """
INDUSTRIES — go into the Icypeas query (currentCompany.industry).
  Examples include: Medical Practices, Hospitals and Health Care, Manufacturing
  Examples exclude: Software Development, Staffing and Recruiting, IT Services
  Leave blank to skip that side.
"""
    )
    ind_inc_raw = input("Industries to INCLUDE (comma-separated, or blank): ").strip()
    ind_exc_raw = input("Industries to EXCLUDE (comma-separated, or blank): ").strip()
    ind_inc = split_pipe_or_comma(ind_inc_raw) if ind_inc_raw else []
    ind_exc = split_pipe_or_comma(ind_exc_raw) if ind_exc_raw else []

    print(
        """
KEYWORDS — go into the Icypeas query (keyword.include / keyword.exclude).
  Use INCLUDE for ICP phrases (e.g. urgent care, CNC machining).
  Use EXCLUDE for noise (e.g. staffing, SaaS, recruiting).
  Leave blank to skip that side.
"""
    )
    kw_inc_raw = input("Keywords to INCLUDE (comma-separated, or blank): ").strip()
    kw_exc_raw = input("Keywords to EXCLUDE (comma-separated, or blank): ").strip()
    kw_inc = split_pipe_or_comma(kw_inc_raw) if kw_inc_raw else []
    kw_exc = split_pipe_or_comma(kw_exc_raw) if kw_exc_raw else []

    if not ind_inc and not ind_exc and not kw_inc and not kw_exc:
        print(
            "\n  Warning: no industries or keywords set. "
            "TAM may be very broad — you can still continue."
        )
        if not ask_yes("Continue without industry/keyword filters?", True):
            print("Stopped. Re-run and add industries and/or keywords.")
            return

    print(
        """
DOMAIN EXCLUDES — put known companies INTO the Icypeas query BEFORE spend
(so you don't pay for rows you already have).

Pick one:
  0) Skip — no domain exclude from databases
  1) Past 15 days leads (Supabase Lead Database + pipeline_leads)
  2) Past 7 days leads (Supabase Lead Database + pipeline_leads)
  3) Existing leads already in PlusVibe campaigns
"""
    )
    while True:
        excl_pick = ask("Type 0, 1, 2, or 3", "1")
        if excl_pick in ("0", "1", "2", "3"):
            break
        print("  Type 0, 1, 2, or 3.")

    source_map = {
        "0": "none",
        "1": "supabase_15d",
        "2": "supabase_7d",
        "3": "plusvibe",
    }
    excl_source = source_map[excl_pick]
    plusvibe_ws = DEFAULT_PLUSVIBE_WS
    plusvibe_camps = ""
    if excl_source == "plusvibe":
        plusvibe_ws = ask("PlusVibe workspace ID", DEFAULT_PLUSVIBE_WS)
        print(
            "\nOptional: limit to specific campaign IDs (comma-separated).\n"
            "Leave blank = exclude leads from ALL campaigns in that workspace."
        )
        if ask_yes("List campaigns in this workspace first?", True):
            run_cmd(
                [
                    sys.executable,
                    str(EXCLUDE_BUILDER),
                    "--source",
                    "plusvibe",
                    "--out",
                    str(EXCLUDE_PATH),
                    "--plusvibe-workspace",
                    plusvibe_ws,
                    "--list-campaigns",
                ]
            )
        plusvibe_camps = input(
            "Campaign IDs to exclude (comma-separated, or blank for ALL): "
        ).strip()

    print(f"\nBuilding exclude seed ({excl_source})…")
    # Cap keeps Icypeas query reliable; newest Supabase domains kept first.
    max_domains = 5000
    if excl_source.startswith("supabase"):
        max_domains = ask_int(
            "Max domains to put in Icypeas query (cap; newest first)", 5000
        )
    build_cmd = [
        sys.executable,
        str(EXCLUDE_BUILDER),
        "--source",
        excl_source,
        "--out",
        str(EXCLUDE_PATH),
        "--max-domains",
        str(max_domains),
    ]
    if excl_source == "plusvibe":
        build_cmd += ["--plusvibe-workspace", plusvibe_ws]
        if plusvibe_camps:
            build_cmd += ["--plusvibe-campaigns", plusvibe_camps]
    rc = run_cmd(build_cmd)
    if rc != 0:
        print("Failed to build exclude seed. Fix the error above and re-run.")
        sys.exit(rc)
    exclude_json = str(EXCLUDE_PATH)
    try:
        seed = json.loads(EXCLUDE_PATH.read_text())
        print(
            f"Exclude seed ready → domains={len(seed.get('domains') or [])} "
            f"linkedins={len(seed.get('linkedins') or [])} "
            f"emails={len(seed.get('emails') or [])}\n"
            "  Domains → Icypeas currentCompanyWebsite.exclude (in-query)\n"
            "  LinkedIns → skipped after search, before Blitz (Icypeas can't exclude them in-query)"
        )
    except Exception:
        pass

    print(
        """
VOLUME MODE — pick one:
  1) READY leads
       Example: \"I need 2000 ready leads\"
       = keep going until that many have email + details

  2) ICYPEAS pull
       Example: \"scrape 2000 Icypeas leads\"
       = pull that many people from Icypeas, then Blitz whatever emails hit
"""
    )
    while True:
        mode_pick = ask("Type 1 for READY, or 2 for ICYPEAS pull", "1")
        if mode_pick in ("1", "2"):
            break
        print("  Type 1 or 2.")

    mode = "ready" if mode_pick == "1" else "pull"
    if mode == "ready":
        n = ask_int("How many READY leads do you want?", 50)
    else:
        n = ask_int("How many Icypeas people should we PULL?", 100)

    pilot = ask_yes("Run a small PILOT first? (recommended)", True)
    if pilot:
        if mode == "ready":
            pilot_n = ask_int("Pilot ready count", min(25, n))
        else:
            pilot_n = ask_int("Pilot Icypeas pull count", min(50, n))
    else:
        pilot_n = n

    cfg = {
        "client": client,
        "titles": titles,
        "title_exclude": title_excl,
        "geo": geo,
        "headcount_min": hc_min,
        "headcount_max": hc_max,
        "keyword_include": kw_inc,
        "keyword_exclude": kw_exc,
        "industry_include": ind_inc,
        "industry_exclude": ind_exc,
        "exclude_json": exclude_json,
        "exclude_source": excl_source,
        "plusvibe_workspace": plusvibe_ws if excl_source == "plusvibe" else None,
        "mode": mode,
        "n": n,
        "pilot_n": pilot_n,
    }
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    print(f"\nSaved answers to: {CONFIG_PATH}")

    # Step: free TAM
    print("\n>>> Step 1/3: FREE TAM (no spend)")
    cmd = [sys.executable, str(RUNNER), "--scope-only", "--config", str(CONFIG_PATH)]
    if exclude_json:
        cmd += ["--exclude-json", exclude_json]
    rc = run_cmd(cmd)
    if rc != 0:
        print("TAM step failed. Fix the error above and re-run the wizard.")
        sys.exit(rc)

    if not ask_yes("Does this TAM look right? Continue to cost quote?", True):
        print("Stopped. Re-run the wizard when ready.")
        return

    # Step: quote
    print("\n>>> Step 2/3: COST QUOTE (no spend)")
    quote_n = pilot_n
    cmd = [sys.executable, str(RUNNER), "--quote-only", "--config", str(CONFIG_PATH)]
    if mode == "ready":
        cmd += ["--ready-target", str(quote_n)]
    else:
        cmd += ["--pull", str(quote_n)]
    if exclude_json:
        cmd += ["--exclude-json", exclude_json]
    rc = run_cmd(cmd)
    if rc != 0:
        sys.exit(rc)

    print(
        "\n>>> Step 3/3: YOUR COST CAP\n"
        "The script will NOT invent a number. You must type the max USD to spend.\n"
        "If spend hits your cap, it stops."
    )
    if not ask_yes("Ready to authorize a PAID pilot/run?", False):
        print("Stopped with no spend. Your config is saved for later.")
        return

    cap = ask_float("Type your hard cost cap in USD (example 2.50)")
    confirm = ask(
        f'Type exactly: confirm {cap:.2f}   (or type cancel)',
        "",
    )
    if confirm.lower() == "cancel":
        print("Cancelled. No spend.")
        return
    if confirm.replace("$", "").strip() != f"confirm {cap:.2f}":
        print("Confirmation text did not match. No spend.")
        return

    cmd = [
        sys.executable,
        str(RUNNER),
        "--config",
        str(CONFIG_PATH),
        "--confirm-spend",
        f"{cap:.2f}",
        "--out-dir",
        str(OUT_DIR),
    ]
    if mode == "ready":
        cmd += ["--ready-target", str(pilot_n)]
    else:
        cmd += ["--pull", str(pilot_n)]
    if exclude_json:
        cmd += ["--exclude-json", exclude_json]

    print(
        f"\nStarting paid run: mode={mode} n={pilot_n} cap=${cap:.2f}\n"
        "Path locked: Icypeas → Blitz only.\n"
    )
    rc = run_cmd(cmd)
    if rc != 0:
        sys.exit(rc)

    print(
        f"""
Done. Look in: {OUT_DIR}
  - latest-ready.csv     (leads with emails)
  - latest-report.json   (spend, ready count, unit economics)

If the pilot looks good and you want the FULL volume ({n}),
re-run the wizard (or ask an agent to run the runner with
--{'ready-target' if mode == 'ready' else 'pull'} {n} --confirm-spend <YOUR NEW CAP>).
"""
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled. No further spend.")
        sys.exit(130)
