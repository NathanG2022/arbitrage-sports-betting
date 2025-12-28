def american_to_decimal(odds: int) -> float:
    """
    Convert American odds to decimal odds.

    Examples:
        +120 -> 2.20
        -150 -> 1.67
    """
    if odds > 0:
        return 1 + odds / 100
    else:
        return 1 + 100 / abs(odds)


def decimal_to_american(decimal_odds: float) -> int:
    """
    Convert decimal odds to American odds.

    Examples:
        2.20 -> +120
        1.67 -> -150
    """
    if decimal_odds >= 2:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


def implied_probability_from_american(odds: int) -> float:
    """
    Convert American odds to implied probability (WITH vig).

    Examples:
        +120 -> 0.4545
        -150 -> 0.6000
    """
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def remove_vig(prob_a: float, prob_b: float):
    """
    Remove vig from a two-outcome market.

    Returns:
        (p_a, p_b) normalized to sum to 1.0
    """
    total = prob_a + prob_b
    if total == 0:
        return 0.0, 0.0
    return prob_a / total, prob_b / total


def arbitrage_roi(decimal_odds_a: float, decimal_odds_b: float) -> float:
    """
    Calculate arbitrage ROI percentage.

    ROI = (1 - (1/d1 + 1/d2)) * 100
    """
    arb_sum = (1 / decimal_odds_a) + (1 / decimal_odds_b)
    if arb_sum >= 1:
        return 0.0
    return (1 - arb_sum) * 100


def arbitrage_stakes(total_investment: float, d1: float, d2: float):
    """
    Calculate stake allocation for guaranteed arbitrage profit.

    Returns:
        stake_1, stake_2, guaranteed_profit
    """
    stake_1 = total_investment * (1 / d1) / ((1 / d1) + (1 / d2))
    stake_2 = total_investment * (1 / d2) / ((1 / d1) + (1 / d2))

    payout = stake_1 * d1
    profit = payout - total_investment

    return round(stake_1, 2), round(stake_2, 2), round(profit, 2)
