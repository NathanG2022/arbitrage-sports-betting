import time
import csv
import os
from datetime import datetime
from typing import Dict
from dotenv import load_dotenv

from odds_api import get_odds
from arb_calc import find_arbitrage

load_dotenv()

MIN_ROI = float(os.getenv("MIN_ROI", 0.0))
OUTPUT_FILE = "arbitrage.csv"

def load_sport_configs():
    raw = os.getenv("SPORT_CONFIGS", "")
    configs = {}
    for item in raw.split(","):
        sport, interval = item.split(":")
        configs[sport.strip()] = int(interval.strip()) * 60
    return configs

SPORT_INTERVALS = load_sport_configs()
last_scan_time: Dict[str, float] = {
    sport: 0.0 for sport in SPORT_INTERVALS.keys()
}

def write_csv(arbs):
    file_exists = os.path.exists(OUTPUT_FILE)

    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "roi",
                "profit",
                "team_1", "team_1_book", "team_1_odds", "team_1_stake",
                "team_2", "team_2_book", "team_2_odds", "team_2_stake",
                "match",
                "sport"
            ]
        )

        if not file_exists:
            writer.writeheader()

        for arb in arbs:
            writer.writerow(arb)


def run_loop():
    all_arbs = []

    for sport, interval in SPORT_INTERVALS.items():
        now = time.time()
        if now - last_scan_time[sport] < interval:
            continue

        print(f"[{datetime.now()}] Scanning {sport}")
        last_scan_time[sport] = now

        try:
            games = get_odds(sport)
            arbs = find_arbitrage(games, MIN_ROI)
            for arb in arbs:
                arb["timestamp"] = datetime.now().isoformat()
                all_arbs.append(arb)
        except Exception as e:
            print(f"Error scanning {sport}: {e}")

    if all_arbs:
        all_arbs.sort(key=lambda x: x["roi"], reverse=True)
        write_csv(all_arbs)
        print(f"Found {len(all_arbs)} arbitrage opportunities.")

    for arb in all_arbs:
        print(
            f"{arb['match']} | ROI: {arb['roi']}% | Profit: ${arb['profit']}\n"
            f"  - {arb['team_1']} @ {arb['team_1_odds']} ({arb['team_1_book']}) "
            f"Stake: ${arb['team_1_stake']}\n"
            f"  - {arb['team_2']} @ {arb['team_2_odds']} ({arb['team_2_book']}) "
            f"Stake: ${arb['team_2_stake']}\n"
        )

if __name__ == "__main__":
    print("Arbitrage scanner started.")
    while True:
        run_loop()
        time.sleep(30)
