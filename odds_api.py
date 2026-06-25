import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

BASE_URL = "https://api.the-odds-api.com/v4"

# Comma-separated Odds API region codes. Defaults to traditional US sportsbooks.
# Toggle to DFS + prediction markets only with REGIONS="us_dfs,us_ex".
#   us_dfs -> DFS sites: prizepicks, underdog, pick6, betr_us_dfs
#   us_ex  -> US exchanges / prediction markets: kalshi, polymarket, novig, prophetx, betopenly
REGIONS = os.getenv("REGIONS", "us")


def get_odds(sport_key: str):
    """
    Fetch moneyline (h2h) odds for a given sport_key from The Odds API.
    Returns raw JSON list of games.
    """
    if not API_KEY:
        raise RuntimeError("ODDS_API_KEY not found in environment variables")

    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": "h2h",
        "oddsFormat": "american",
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()

    return resp.json()
