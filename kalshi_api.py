"""Public (unauthenticated) client for the Kalshi trade API.

Reads markets/events/prices, which Kalshi exposes without authentication.
Order-book depth and trading require RSA-PSS request signing and are NOT
implemented here (read-only by design).

Prices come back as dollar strings/floats in [0, 1] representing probability
(e.g. "0.4500" = 45% implied probability = decimal odds 1 / 0.45).
"""
import os

import requests
from dotenv import load_dotenv

from utils import decimal_to_american

load_dotenv()

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://external-api.kalshi.com/trade-api/v2")
TIMEOUT = 20


def _to_float(value):
    """Kalshi returns prices as strings or floats; coerce safely. None -> None."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get(path: str, params: dict) -> dict:
    resp = requests.get(
        f"{BASE_URL}{path}",
        params=params,
        headers={"Accept": "application/json"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _paginate(path: str, params: dict, list_key: str) -> list:
    """Follow Kalshi's cursor pagination until exhausted."""
    out = []
    cursor = ""
    while True:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        data = _get(path, page_params)
        out.extend(data.get(list_key, []) or [])
        cursor = data.get("cursor", "") or ""
        if not cursor:
            break
    return out


def exchange_status() -> dict:
    """GET /exchange/status — pre-flight check (no auth).

    Returns flags like exchange_active / trading_active.
    """
    return _get("/exchange/status", {})


def get_markets(status: str = "open", mve_filter: str = "exclude", **filters) -> list:
    """GET /markets (public). Auto-paginated.

    Common filters: series_ticker, event_ticker, tickers (comma-separated).
    mve_filter="exclude" drops multivariate (parlay) markets.
    """
    params = {"limit": 1000, "status": status, "mve_filter": mve_filter}
    params.update({k: v for k, v in filters.items() if v is not None})
    return _paginate("/markets", params, "markets")


def get_events(
    status: str = "open", with_nested_markets: bool = True, **filters
) -> list:
    """GET /events (public). Auto-paginated. Each event embeds its markets."""
    params = {
        "limit": 200,
        "status": status,
        "with_nested_markets": str(with_nested_markets).lower(),
    }
    params.update({k: v for k, v in filters.items() if v is not None})
    return _paginate("/events", params, "events")


def price_to_decimal(prob: float):
    """Convert a Kalshi probability price (0..1) to decimal odds. None if invalid."""
    if not prob or prob <= 0:
        return None
    return 1.0 / prob


def to_odds_api_format(events: list) -> list:
    """Adapt Kalshi events into The-Odds-API game shape so the existing 2-way
    arbitrage engine (arb_calc.find_arbitrage) can compare real Kalshi asks
    against other books.

    Uses yes_ask (the price you actually pay to buy a YES contract), not mid.
    Only 2-outcome events map cleanly to the h2h engine; N-way events are left
    for kalshi_arb.find_within_event_arbs.
    """
    games = []
    for event in events:
        markets = [m for m in event.get("markets", []) if m.get("status") == "active"]
        outcomes = []
        for m in markets:
            ask = _to_float(m.get("yes_ask_dollars"))
            # Exclude degenerate prices: 0 (no odds) and >=1 (decimal_to_american
            # divides by decimal-1, which is 0 at prob=1.0).
            if ask is None or ask <= 0 or ask >= 1:
                continue
            dec = price_to_decimal(ask)
            name = m.get("yes_sub_title") or m.get("title") or m.get("ticker")
            outcomes.append({"name": name, "price": decimal_to_american(dec)})

        if len(outcomes) != 2:
            continue

        games.append({
            "home_team": outcomes[0]["name"],
            "away_team": outcomes[1]["name"],
            "commence_time": None,
            "sport_key": event.get("series_ticker"),
            "bookmakers": [{
                "title": "Kalshi",
                "markets": [{"key": "h2h", "outcomes": outcomes}],
            }],
        })
    return games
