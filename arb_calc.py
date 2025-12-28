import os
from datetime import datetime, timezone
from utils import american_to_decimal, arbitrage_stakes

TOTAL_STAKE = float(os.getenv("TOTAL_STAKE", 1000.0))
SLIPPAGE_CUTOFF_MINUTES = int(os.getenv("SLIPPAGE_CUTOFF_MINUTES", 15))

def find_arbitrage(games, min_roi=0.0):
    """
    Find arbitrage opportunities from Odds API game list.

    Returns:
        List[dict] sorted by ROI desc
    """
    opportunities = []

    for game in games:

        commence_time = game.get("commence_time")
        if commence_time:
            game_time = datetime.fromisoformat(
                commence_time.replace("Z", "+00:00")
            )
            now_utc = datetime.now(timezone.utc)
            minutes_to_start = (game_time - now_utc).total_seconds() / 60

            if minutes_to_start < SLIPPAGE_CUTOFF_MINUTES:
                # continue
                print(f"Skipping {game.get('home_team')} vs {game.get('away_team')} - "
                      f"starts in {minutes_to_start:.1f} minutes")

        bookmakers = game.get("bookmakers", [])
        if not bookmakers:
            continue

        # team_name -> best odds info
        best_prices = {}

        for book in bookmakers:
            book_name = book.get("title", "Unknown")

            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                for outcome in market.get("outcomes", []):
                    team = outcome.get("name")
                    american_odds = outcome.get("price")

                    if team is None or american_odds is None:
                        continue

                    dec_odds = american_to_decimal(american_odds)

                    # Keep the BEST price for each team
                    if team not in best_prices or dec_odds > best_prices[team]["decimal"]:
                        best_prices[team] = {
                            "decimal": dec_odds,
                            "american": american_odds,
                            "book": book_name,
                        }

        # Moneyline arbitrage requires exactly 2 outcomes
        if len(best_prices) != 2:
            continue

        teams = list(best_prices.keys())
        d1 = best_prices[teams[0]]["decimal"]
        d2 = best_prices[teams[1]]["decimal"]

        arb_sum = (1 / d1) + (1 / d2)

        if arb_sum < 1:
            roi = (1 - arb_sum) * 100

            if roi >= min_roi:
                stake_1, stake_2, profit = arbitrage_stakes(
                    TOTAL_STAKE,
                    d1,
                    d2
                )
                opportunities.append({
                    "roi": round(roi, 2),
                    "profit": profit,
                    "match": f"{teams[0]} vs {teams[1]}",
                    "team_1": teams[0],
                    "team_1_book": best_prices[teams[0]]["book"],
                    "team_1_odds": best_prices[teams[0]]["american"],
                    "team_1_stake": stake_1,
                    "team_2": teams[1],
                    "team_2_book": best_prices[teams[1]]["book"],
                    "team_2_odds": best_prices[teams[1]]["american"],
                    "team_2_stake": stake_2,
                    "sport": game.get("sport_key"),
                })

    return sorted(opportunities, key=lambda x: x["roi"], reverse=True)
