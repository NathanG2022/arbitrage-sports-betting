"""Pluggable notification channels for arbitrage alerts.

Currently ships a Discord webhook notifier. To add a new channel (e.g. Gmail,
iMessage), add a Notifier subclass and a branch in load_notifiers() — the scan
loop in main.py does not need to change.
"""
import os

import requests


class Notifier:
    """Base notifier interface. Subclasses implement send()."""

    name = "base"

    def send(self, title: str, body: str) -> None:
        raise NotImplementedError


class DiscordNotifier(Notifier):
    """Posts alerts to a Discord channel via an incoming webhook URL."""

    name = "discord"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, body: str) -> None:
        content = f"**{title}**\n{body}"
        try:
            resp = requests.post(
                self.webhook_url,
                json={"content": content},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as e:
            # A failed notification must never crash the scanner.
            print(f"[notifier:discord] failed to send alert: {e}")


def load_notifiers():
    """Build the list of enabled notifiers from environment config.

    NOTIFY_CHANNELS is a comma-separated list of channel names (default
    "discord"). A channel is only enabled if its required config is present.
    """
    channels = os.getenv("NOTIFY_CHANNELS", "discord")
    notifiers = []

    for raw in channels.split(","):
        name = raw.strip().lower()
        if not name:
            continue

        if name == "discord":
            webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
            if not webhook_url:
                print(
                    "[notifier] DISCORD_WEBHOOK_URL not set — Discord alerts disabled"
                )
                continue
            notifiers.append(DiscordNotifier(webhook_url))
        else:
            print(f"[notifier] unknown channel '{name}' — skipping")

    if not notifiers:
        print("[notifier] no notification channels enabled")

    return notifiers


def format_arb(arb: dict):
    """Build a (title, body) pair from an arbitrage opportunity dict.

    Supports two shapes:
      - N-leg (within-Kalshi): a `legs` list of {name, book, odds, stake}.
      - 2-way (cross-book): team_1/team_2 fields as written by arb_calc.
    """
    title = f"Arb {arb['roi']}% ROI — {arb['match']} ({arb.get('sport', 'unknown')})"

    if arb.get("legs"):
        lines = [
            f"{leg['name']} @ {leg['odds']} ({leg['book']})  stake ${leg['stake']}"
            for leg in arb["legs"]
        ]
        extra = ""
        if arb.get("gross_roi") is not None:
            extra = (
                f" (gross {arb['gross_roi']}%"
                + (f", fees ${arb['fees']}" if arb.get("fees") is not None else "")
                + ")"
            )
        body = (
            f"Profit: ${arb['profit']} on configured stake{extra}\n"
            f"```\n" + "\n".join(lines) + "\n```"
        )
        return title, body

    body = (
        f"Profit: ${arb['profit']} on configured stake\n"
        f"```\n"
        f"{arb['team_1']} @ {arb['team_1_odds']} ({arb['team_1_book']})  "
        f"stake ${arb['team_1_stake']}\n"
        f"{arb['team_2']} @ {arb['team_2_odds']} ({arb['team_2_book']})  "
        f"stake ${arb['team_2_stake']}\n"
        f"```"
    )
    return title, body
