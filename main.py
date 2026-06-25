import time
import csv
import json
import os
from datetime import datetime
from typing import Dict
from dotenv import load_dotenv

from odds_api import get_odds
from arb_calc import find_arbitrage
from notifier import load_notifiers, format_arb
import kalshi_api
from kalshi_arb import find_within_event_arbs

load_dotenv()

MIN_ROI = float(os.getenv("MIN_ROI", 0.0))
OUTPUT_FILE = "arbitrage.csv"

# Scan Kalshi directly (public API, real bid/ask) in addition to The Odds API.
SCAN_KALSHI = os.getenv("SCAN_KALSHI", "false").lower() == "true"
# Optional comma-separated Kalshi series tickers to restrict the scan (else all).
KALSHI_SERIES = [s.strip() for s in os.getenv("KALSHI_SERIES", "").split(",") if s.strip()]

# Push a notification for any opportunity at/above this ROI (percent).
# Independent of MIN_ROI, which only gates CSV/console output.
ALERT_ROI = float(os.getenv("ALERT_ROI", 3.0))
# Re-alert the same match + book pair at most once per this many minutes.
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", 60))

NOTIFIERS = load_notifiers()
# alert key -> last-sent epoch seconds
_alerted: Dict[str, float] = {}


def _alert_key(arb) -> str:
    if arb.get("legs"):
        parts = sorted(f"{l['book']}:{l['name']}" for l in arb["legs"])
        return arb["match"] + "|" + "|".join(parts)
    return f"{arb['match']}|{arb['team_1_book']}|{arb['team_2_book']}"


def send_alerts(arbs):
    """Notify on opportunities >= ALERT_ROI, de-duped by cooldown."""
    if not NOTIFIERS:
        return

    now = time.time()
    cooldown = ALERT_COOLDOWN_MINUTES * 60

    for arb in arbs:
        if arb["roi"] < ALERT_ROI:
            continue

        key = _alert_key(arb)
        last = _alerted.get(key)
        if last is not None and now - last < cooldown:
            continue

        title, body = format_arb(arb)
        for notifier in NOTIFIERS:
            notifier.send(title, body)
        _alerted[key] = now
        print(f"  alerted: {arb['match']} ({arb['roi']}% ROI)")

def load_sport_configs():
    raw = os.getenv("SPORT_CONFIGS", "")
    configs = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        sport, interval = item.split(":", 1)
        sport = sport.strip()
        interval = interval.strip()
        if not sport or not interval.isdigit():
            print(f"[config] skipping malformed SPORT_CONFIGS entry: '{item}'")
            continue
        configs[sport] = int(interval) * 60
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
                "sport",
                "legs",  # JSON for N-leg (within-Kalshi) arbs; empty for 2-way
            ],
            extrasaction="ignore",  # tolerate extra keys (gross_roi, fees, ...)
        )

        if not file_exists:
            writer.writeheader()

        for arb in arbs:
            row = dict(arb)
            if isinstance(row.get("legs"), list):
                row["legs"] = json.dumps(row["legs"])
            writer.writerow(row)


def _norm(name) -> str:
    return "".join(c for c in (name or "").lower() if c.isalnum())


def scan_kalshi():
    """Scan Kalshi directly. Returns (within_event_arbs, team_index).

    team_index maps frozenset of the two normalized outcome names -> a Kalshi
    "bookmaker" dict (Odds-API shape), for merging real Kalshi prices into the
    cross-venue 2-way engine.
    """
    status = kalshi_api.exchange_status()
    if not status.get("trading_active", True):
        print("[kalshi] trading inactive — skipping Kalshi scan")
        return [], {}

    if KALSHI_SERIES:
        events = []
        for st in KALSHI_SERIES:
            events.extend(kalshi_api.get_events(series_ticker=st))
    else:
        events = kalshi_api.get_events()
    print(f"[kalshi] {len(events)} open events")

    within = find_within_event_arbs(events, MIN_ROI)
    for arb in within:
        arb["timestamp"] = datetime.now().isoformat()

    team_index = {}
    for game in kalshi_api.to_odds_api_format(events):
        book = game["bookmakers"][0]
        names = frozenset(_norm(o["name"]) for o in book["markets"][0]["outcomes"])
        team_index[names] = book
    return within, team_index


def run_loop():
    all_arbs = []

    kalshi_index = {}
    if SCAN_KALSHI:
        print(f"[{datetime.now()}] Scanning Kalshi")
        try:
            kalshi_arbs, kalshi_index = scan_kalshi()
            all_arbs.extend(kalshi_arbs)
        except Exception as e:
            print(f"Error scanning Kalshi: {e}")

    for sport, interval in SPORT_INTERVALS.items():
        now = time.time()
        if now - last_scan_time[sport] < interval:
            continue

        print(f"[{datetime.now()}] Scanning {sport}")
        last_scan_time[sport] = now

        try:
            games = get_odds(sport)
            # Merge real Kalshi prices into matching games (by team-name set).
            if kalshi_index:
                for game in games:
                    names = frozenset((_norm(game.get("home_team")),
                                       _norm(game.get("away_team"))))
                    book = kalshi_index.get(names)
                    if book:
                        game.setdefault("bookmakers", []).append(book)
            arbs = find_arbitrage(games, MIN_ROI)
            for arb in arbs:
                arb["timestamp"] = datetime.now().isoformat()
                all_arbs.append(arb)
        except Exception as e:
            print(f"Error scanning {sport}: {e}")

    if all_arbs:
        all_arbs.sort(key=lambda x: x["roi"], reverse=True)
        write_csv(all_arbs)
        send_alerts(all_arbs)
        print(f"Found {len(all_arbs)} arbitrage opportunities.")

    for arb in all_arbs:
        header = f"{arb['match']} | ROI: {arb['roi']}% | Profit: ${arb['profit']}"
        if arb.get("legs"):
            lines = "\n".join(
                f"  - {l['name']} @ {l['odds']} ({l['book']}) Stake: ${l['stake']}"
                for l in arb["legs"]
            )
            print(f"{header}\n{lines}\n")
        else:
            print(
                f"{header}\n"
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
