"""One-shot arbitrage scan for a fixed set of sports.

Forces DFS + prediction-market regions (us_dfs, us_ex) unless REGIONS is
already set in the environment. Runs a single pass and prints opportunities
instead of looping like main.py.

Usage:
    python scan_once.py
"""
import os

# Default this run to DFS + prediction markets only (can be overridden by env).
os.environ.setdefault("REGIONS", "us_dfs,us_ex")

from datetime import datetime

from odds_api import get_odds, REGIONS
from arb_calc import find_arbitrage

SPORTS = [
    "basketball_nba",
    "americanfootball_nfl",
    "baseball_mlb",
    "soccer_epl",
]

MIN_ROI = float(os.getenv("MIN_ROI", 0.0))


def main():
    print(f"One-shot scan | regions={REGIONS} | min_roi={MIN_ROI}%")
    all_arbs = []

    for sport in SPORTS:
        print(f"[{datetime.now():%H:%M:%S}] Scanning {sport} ...")
        try:
            games = get_odds(sport)
        except Exception as e:
            print(f"  error: {e}")
            continue

        print(f"  {len(games)} games returned")
        arbs = find_arbitrage(games, MIN_ROI)
        for arb in arbs:
            arb["sport"] = sport
        all_arbs.extend(arbs)

    print()
    if not all_arbs:
        print("No arbitrage opportunities found across DFS + prediction markets.")
        return

    all_arbs.sort(key=lambda x: x["roi"], reverse=True)
    print(f"Found {len(all_arbs)} opportunities:\n")
    for arb in all_arbs:
        print(
            f"{arb['match']} [{arb['sport']}] | ROI: {arb['roi']}% | Profit: ${arb['profit']}\n"
            f"  - {arb['team_1']} @ {arb['team_1_odds']} ({arb['team_1_book']}) "
            f"Stake: ${arb['team_1_stake']}\n"
            f"  - {arb['team_2']} @ {arb['team_2_odds']} ({arb['team_2_book']}) "
            f"Stake: ${arb['team_2_stake']}\n"
        )


if __name__ == "__main__":
    main()
