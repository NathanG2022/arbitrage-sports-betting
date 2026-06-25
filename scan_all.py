"""One-shot arbitrage scan across EVERY active sport and EVERY book/region.

Plain output: prints opportunities to the terminal and appends to arbitrage.csv.
No dashboard, no loop — run it whenever you want a full sweep.

    python scan_all.py
"""
import os
import csv
from datetime import datetime

import requests
from dotenv import load_dotenv

from arb_calc import find_arbitrage
from notifier import discord_from_env, send_digest

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"
MIN_ROI = float(os.getenv("MIN_ROI", 0.0))
OUTPUT_FILE = "arbitrage.csv"

# Books accessible to a California resident. CA has no legal online sportsbooks,
# so this defaults to federally-regulated prediction markets / exchanges + DFS.
# Polymarket is excluded by default (geo-blocks US users); add it if you use it.
# Matched case-insensitively as a substring of the book name. Configure in .env.
CA_LEGAL_BOOKS = [
    b.strip().lower() for b in os.getenv(
        "CA_LEGAL_BOOKS",
        "Kalshi,Novig,ProphetX,BetOpenly,PrizePicks,Underdog,Pick6,Betr",
    ).split(",") if b.strip()
]


def _ca_legal_book(book: str) -> bool:
    b = (book or "").lower()
    return any(allowed in b for allowed in CA_LEGAL_BOOKS)


def _is_ca_legal(arb: dict) -> bool:
    """True only if BOTH legs are on California-accessible venues."""
    return _ca_legal_book(arb["team_1_book"]) and _ca_legal_book(arb["team_2_book"])

# Every book/region the API exposes. This scanner always sweeps them all
# (it deliberately ignores the .env REGIONS used by the targeted scanners).
ALL_REGIONS = "us,us2,us_dfs,us_ex,uk,eu,au"

FIELDS = [
    "timestamp", "roi", "profit",
    "team_1", "team_1_book", "team_1_odds", "team_1_stake",
    "team_2", "team_2_book", "team_2_odds", "team_2_stake",
    "match", "sport",
]


def active_sports():
    r = requests.get(f"{BASE_URL}/sports", params={"apiKey": API_KEY}, timeout=15)
    r.raise_for_status()
    return [s["key"] for s in r.json() if s.get("active")]


def get_odds(sport):
    r = requests.get(
        f"{BASE_URL}/sports/{sport}/odds",
        params={"apiKey": API_KEY, "regions": ALL_REGIONS,
                "markets": "h2h", "oddsFormat": "american"},
        timeout=20,
    )
    remaining = r.headers.get("x-requests-remaining")
    if r.status_code != 200:
        return [], remaining
    return r.json(), remaining


def write_csv(arbs):
    exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for a in arbs:
            w.writerow(a)


def main():
    if not API_KEY:
        raise SystemExit("ODDS_API_KEY not set in .env")

    sports = active_sports()
    print(f"Scanning {len(sports)} active sports across regions: {ALL_REGIONS}\n")

    all_arbs = []
    remaining = "?"
    for sport in sports:
        games, remaining = get_odds(sport)
        arbs = find_arbitrage(games, MIN_ROI)
        for a in arbs:
            a["timestamp"] = datetime.now().isoformat()
            a["sport"] = sport
        if arbs:
            print(f"  {sport:42s} {len(games):3d} games  ->  {len(arbs)} arb(s)")
        all_arbs.extend(arbs)

    all_arbs.sort(key=lambda x: x["roi"], reverse=True)

    print("\n" + "=" * 70)
    if not all_arbs:
        print("No arbitrage opportunities found.")
    else:
        print(f"{len(all_arbs)} ARBITRAGE OPPORTUNITIES (all sports, all books)\n")
        for a in all_arbs:
            print(
                f"{a['roi']:+6.2f}% | ${a['profit']:>7.2f} | {a['sport']}\n"
                f"   {a['match']}\n"
                f"     {a['team_1']} @ {a['team_1_odds']:+d} ({a['team_1_book']})  stake ${a['team_1_stake']}\n"
                f"     {a['team_2']} @ {a['team_2_odds']:+d} ({a['team_2_book']})  stake ${a['team_2_stake']}\n"
            )
        write_csv(all_arbs)
        print(f"Wrote {len(all_arbs)} rows to {OUTPUT_FILE}")

        # --- sync to Discord ---
        main_hook = discord_from_env("DISCORD_WEBHOOK_URL")
        cali_hook = discord_from_env("CALI_DISCORD_WEBHOOK_URL")

        sent = send_digest(main_hook, all_arbs,
                           f"🎯 {len(all_arbs)} arbs — all sports & books")
        if main_hook:
            print(f"Synced {sent} arbs to Discord (all books)")
        else:
            print("DISCORD_WEBHOOK_URL not set — skipped Discord sync")

        cali = [a for a in all_arbs if _is_ca_legal(a)]
        sent_ca = send_digest(cali_hook, cali,
                              f"🐻 {len(cali)} California-legal arbs")
        if cali_hook:
            print(f"Synced {sent_ca} CA-legal arbs to CALI_DISCORD_WEBHOOK_URL")
        elif cali:
            print(f"{len(cali)} CA-legal arbs found but CALI_DISCORD_WEBHOOK_URL not set")

    print(f"API credits remaining: {remaining}")


if __name__ == "__main__":
    main()
