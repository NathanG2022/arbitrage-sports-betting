"""Within-Kalshi multi-outcome arbitrage.

For a mutually-exclusive, collectively-exhaustive Kalshi event, buying one YES
contract of every outcome guarantees a $1 payout (exactly one outcome resolves
YES). If the total cost (sum of yes_ask) is below $1, that's a locked profit
executable entirely on Kalshi.

This generalizes arb_calc.find_arbitrage (which only handles exactly 2 outcomes)
to N outcomes, and accounts for Kalshi trading fees.
"""
import math
import os

from dotenv import load_dotenv

from utils import decimal_to_american
from kalshi_api import _to_float, price_to_decimal

load_dotenv()

TOTAL_STAKE = float(os.getenv("TOTAL_STAKE", 1000.0))
# Kalshi's standard fee: ceil(rate * C * P * (1-P)) per leg, C contracts at price P.
FEE_RATE = float(os.getenv("KALSHI_FEE_RATE", 0.07))
# Minimum resting ask size (contracts) required on EVERY leg — can't fill where
# there is no offer.
MIN_ASK_SIZE = float(os.getenv("KALSHI_MIN_ASK_SIZE", 1.0))
# Minimum sum of yes_ask across an event's outcomes to treat the set as
# collectively exhaustive. A Dutch-book arb is only real if the listed outcomes
# cover the whole probability space, in which case sum_ask sits JUST below 1.
# A low sum (e.g. 0.06) means the favorite/other outcomes are missing from the
# set — not free money. Genuine arbs on liquid markets are always thin, so this
# floor rejects non-exhaustive sets without discarding real opportunities.
MIN_SUM_ASK = float(os.getenv("KALSHI_MIN_SUM_ASK", 0.90))


def _leg_fee(contracts: float, price: float) -> float:
    """Kalshi trading fee for `contracts` YES at `price` dollars, rounded up to a cent."""
    cents = math.ceil(FEE_RATE * contracts * price * (1 - price) * 100)
    return cents / 100.0


def find_within_event_arbs(events, min_roi=0.0, total_stake=None):
    """Find within-event arbs across Kalshi events.

    Args:
        events: Kalshi events (with nested markets), e.g. from kalshi_api.get_events.
        min_roi: minimum NET ROI percent to report.
        total_stake: total dollars to deploy per opportunity (default env TOTAL_STAKE).

    Returns:
        List[dict] sorted by net ROI desc. Each dict carries a `legs` list and is
        shaped for notifier.format_arb.
    """
    if total_stake is None:
        total_stake = TOTAL_STAKE

    opportunities = []

    for event in events:
        # Gate strictly: only events Kalshi marks mutually exclusive can be treated
        # as "exactly one outcome resolves YES". Anything else => skip (no false arbs).
        if not event.get("mutually_exclusive"):
            continue

        markets = [m for m in event.get("markets", []) if m.get("status") == "active"]
        if len(markets) < 2:
            continue

        legs = []
        valid = True
        for m in markets:
            ask = _to_float(m.get("yes_ask_dollars"))
            ask_size = _to_float(m.get("yes_ask_size_fp")) or 0.0
            # Every leg must be real: priced in (0,1) AND have fillable resting size.
            if ask is None or ask <= 0 or ask >= 1 or ask_size < MIN_ASK_SIZE:
                valid = False
                break
            legs.append({
                "name": m.get("yes_sub_title") or m.get("title") or m.get("ticker"),
                "ticker": m.get("ticker"),
                "price": ask,  # probability in dollars
                "ask_size": ask_size,
            })
        if not valid or len(legs) < 2:
            continue

        sum_ask = sum(leg["price"] for leg in legs)
        if sum_ask >= 1.0:
            continue  # no arbitrage
        if sum_ask < MIN_SUM_ASK:
            # Outcome set not collectively exhaustive (missing outcomes) — the
            # sub-1 sum is an artifact, not a real arb. Skip.
            continue

        gross_roi = (1.0 / sum_ask - 1.0) * 100.0

        # Scale to the stake budget: buy `units` contracts of each outcome.
        units = total_stake / sum_ask
        total_fees = 0.0
        for leg in legs:
            stake = units * leg["price"]
            leg["stake"] = round(stake, 2)
            leg["odds"] = decimal_to_american(price_to_decimal(leg["price"]))
            leg["book"] = "Kalshi"
            total_fees += _leg_fee(units, leg["price"])

        cost = units * sum_ask                       # == total_stake
        gross_profit = units * (1.0 - sum_ask)       # payout(units) - cost
        net_profit = gross_profit - total_fees
        net_roi = net_profit / cost * 100.0

        if net_roi < min_roi:
            continue

        opportunities.append({
            "match": event.get("title", event.get("event_ticker", "Unknown")),
            "sport": event.get("series_ticker"),
            "roi": round(net_roi, 3),
            "gross_roi": round(gross_roi, 3),
            "profit": round(net_profit, 2),
            "fees": round(total_fees, 2),
            "sum_ask": round(sum_ask, 4),
            "n_outcomes": len(legs),
            "legs": [
                {"name": l["name"], "book": l["book"], "odds": l["odds"],
                 "stake": l["stake"], "price": round(l["price"], 4),
                 "ask_size": l["ask_size"]}
                for l in legs
            ],
        })

    return sorted(opportunities, key=lambda x: x["roi"], reverse=True)
