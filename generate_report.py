"""Scan every sportsbook (all Odds API regions) + Kalshi direct, and emit a
self-contained HTML arbitrage dashboard styled like a pro odds tool.

Usage:
    python generate_report.py            # writes report.html
"""
import os
import json
import html
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from utils import american_to_decimal, decimal_to_american, arbitrage_stakes
import kalshi_api
from kalshi_arb import find_within_event_arbs

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"
TOTAL_STAKE = float(os.getenv("TOTAL_STAKE", 1000.0))

# Every sportsbook the API exposes: US books, exchanges, DFS, and intl.
ALL_REGIONS = "us,us2,us_dfs,us_ex,uk,eu,au"

# Active sports most likely to have live two-way markets right now.
SPORTS = [
    "baseball_mlb", "soccer_fifa_world_cup", "basketball_wnba",
    "tennis_wta_bad_homburg_open", "mma_mixed_martial_arts",
    "cricket_international_t20", "soccer_brazil_campeonato",
    "soccer_italy_serie_a", "baseball_kbo", "baseball_npb",
]


def scan_odds_api():
    opps = []
    remaining = None
    for sport in SPORTS:
        try:
            resp = requests.get(
                f"{BASE_URL}/sports/{sport}/odds",
                params={"apiKey": API_KEY, "regions": ALL_REGIONS,
                        "markets": "h2h", "oddsFormat": "american"},
                timeout=20,
            )
            remaining = resp.headers.get("x-requests-remaining", remaining)
            resp.raise_for_status()
            games = resp.json()
        except Exception as e:
            print(f"  [odds] {sport}: {e}")
            continue

        for game in games:
            best = {}      # outcome -> best price info
            decs = {}      # outcome -> [decimal odds across books]
            for book in game.get("bookmakers", []):
                title = book.get("title", "?")
                for market in book.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for o in market.get("outcomes", []):
                        name, price = o.get("name"), o.get("price")
                        if name is None or price is None:
                            continue
                        d = american_to_decimal(price)
                        decs.setdefault(name, []).append(d)
                        if name not in best or d > best[name]["decimal"]:
                            best[name] = {"decimal": d, "american": price, "book": title}

            if len(best) != 2:
                continue
            names = list(best)
            d1, d2 = best[names[0]]["decimal"], best[names[1]]["decimal"]
            s = 1 / d1 + 1 / d2
            if s >= 1:
                continue
            roi = (1 - s) * 100
            st1, st2, profit = arbitrage_stakes(TOTAL_STAKE, d1, d2)

            def mavg(n):
                arr = decs[n]
                return decimal_to_american(sum(arr) / len(arr))

            opps.append({
                "source": "odds",
                "sport": sport,
                "market": "Moneyline",
                "match": f"{names[0]} vs {names[1]}",
                "commence": game.get("commence_time"),
                "roi": round(roi, 2),
                "profit": round(profit, 2),
                "n_books": len(set(b["book"] for b in best.values())),
                "legs": [
                    {"book": best[names[0]]["book"], "name": names[0],
                     "odds": best[names[0]]["american"], "mkt_avg": mavg(names[0]),
                     "stake": st1, "payout": round(st1 * d1, 2)},
                    {"book": best[names[1]]["book"], "name": names[1],
                     "odds": best[names[1]]["american"], "mkt_avg": mavg(names[1]),
                     "stake": st2, "payout": round(st2 * d2, 2)},
                ],
            })
    return opps, remaining


def scan_kalshi():
    out = []
    try:
        events = kalshi_api.get_events()
    except Exception as e:
        print(f"  [kalshi] {e}")
        return out
    for a in find_within_event_arbs(events, min_roi=0.0):
        out.append({
            "source": "kalshi",
            "sport": a["sport"],
            "market": "Multi-outcome (Kalshi)",
            "match": a["match"],
            "commence": None,
            "roi": a["roi"],
            "gross_roi": a.get("gross_roi"),
            "profit": a["profit"],
            "n_books": 1,
            "legs": [
                {"book": "Kalshi", "name": l["name"], "odds": l["odds"],
                 "mkt_avg": None, "stake": l["stake"], "payout": None}
                for l in a["legs"]
            ],
        })
    return out


def render(opps, meta):
    opps = sorted(opps, key=lambda x: x["roi"], reverse=True)
    cards = "\n".join(render_card(o) for o in opps)
    data_json = html.escape(json.dumps(meta))
    return TEMPLATE.replace("{{CARDS}}", cards or EMPTY) \
                   .replace("{{COUNT}}", str(len(opps))) \
                   .replace("{{GENERATED}}", meta["generated"]) \
                   .replace("{{REMAINING}}", str(meta["remaining"])) \
                   .replace("{{BOOKS}}", str(meta["books"])) \
                   .replace("{{META}}", data_json)


def chip(book):
    initials = "".join(w[0] for w in book.split()[:2]).upper()[:2] or "?"
    # deterministic hue from book name
    hue = sum(ord(c) for c in book) % 360
    return (f'<span class="chip" style="--h:{hue}">{html.escape(initials)}</span>'
            f'<span class="bk">{html.escape(book)}</span>')


def fmt_odds(v):
    return f"+{v}" if isinstance(v, (int, float)) and v > 0 else str(v)


def leg_row(leg, first):
    mkt = (f'<span class="mkt">Mkt avg {fmt_odds(leg["mkt_avg"])}</span>'
           if leg.get("mkt_avg") is not None else "")
    payout = (f'<div class="cell pay"><span class="lbl">Payout</span>'
              f'<span class="val">${leg["payout"]:,.2f}</span></div>'
              if leg.get("payout") is not None else
              '<div class="cell pay"><span class="lbl">Payout</span>'
              '<span class="val">$1,000.00</span></div>')
    tag = '<span class="first">Bet First</span>' if first else ""
    return f"""
      <div class="leg">
        <div class="book">{chip(leg['book'])}</div>
        <div class="sel">
          <span class="pick">{html.escape(str(leg['name']))}</span>
          <span class="od">{fmt_odds(leg['odds'])}</span>
          {mkt}{tag}
        </div>
        <div class="cell"><span class="lbl">Bet size</span><span class="val">${leg['stake']:,.2f}</span></div>
        {payout}
        <button class="bet">Bet</button>
      </div>"""


def render_card(o):
    when = ""
    if o.get("commence"):
        try:
            dt = datetime.fromisoformat(o["commence"].replace("Z", "+00:00"))
            when = dt.strftime("%a %-m/%-d @ %-I:%M%p UTC")
        except Exception:
            when = o["commence"]
    legs = "".join(leg_row(l, i == 1) for i, l in enumerate(o["legs"]))
    gross = (f' · {o["gross_roi"]}% gross' if o.get("gross_roi") is not None else "")
    src = "exchange/dfs/book" if o["source"] == "odds" else "kalshi"
    return f"""
    <article class="card" data-src="{o['source']}">
      <header class="ch">
        <div class="title">
          <span class="sport">{html.escape(o['sport'])}</span>
          <span class="match">{html.escape(o['match'])}</span>
          <span class="sub">{html.escape(o['market'])}{(' · ' + when) if when else ''}</span>
        </div>
        <div class="roi">+${o['profit']:,.2f}<span>·</span>{o['roi']}% ROI{gross}</div>
      </header>
      <div class="legs">{legs}</div>
      <button class="both">Place Both</button>
    </article>"""


EMPTY = '<p class="empty">No arbitrage opportunities right now. Re-run to refresh.</p>'

TEMPLATE = r"""<title>Arbitrage Board</title>
<style>
  :root{
    --bg:#0a0e14; --panel:#121826; --panel2:#0f1521; --line:#1e2738;
    --ink:#e8edf6; --dim:#8893a7; --green:#3ddc97; --green-d:#0f3a2c;
    --blue:#3b82f6; --chip:#1b2435;
  }
  *{box-sizing:border-box}
  body{margin:0;background:
      radial-gradient(1200px 600px at 80% -10%, #16203200, #0a0e14),
      var(--bg);
    color:var(--ink);
    font:15px/1.4 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased}
  .wrap{max-width:1040px;margin:0 auto;padding:28px 20px 80px}
  .top{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;
    flex-wrap:wrap;margin-bottom:24px}
  h1{font-size:22px;font-weight:700;letter-spacing:-.02em;margin:0}
  h1 b{color:var(--green)}
  .lead{color:var(--dim);font-size:13px;margin-top:6px;max-width:62ch}
  .stats{display:flex;gap:10px;flex-wrap:wrap}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:8px 12px;font-variant-numeric:tabular-nums}
  .stat .n{font-weight:700;font-size:16px}
  .stat .k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
  .filters{display:flex;gap:8px;margin:0 0 18px}
  .filters button{background:var(--panel);border:1px solid var(--line);color:var(--dim);
    padding:6px 14px;border-radius:999px;font-size:13px;cursor:pointer}
  .filters button.on{color:var(--ink);border-color:var(--green);background:var(--green-d)}

  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;
    margin-bottom:14px;overflow:hidden}
  .ch{display:flex;justify-content:space-between;align-items:center;gap:14px;
    padding:14px 16px;border-bottom:1px solid var(--line)}
  .title{display:flex;flex-direction:column;gap:2px;min-width:0}
  .sport{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}
  .match{font-weight:600;font-size:15px}
  .sub{font-size:12px;color:var(--dim)}
  .roi{flex:none;font-weight:700;font-size:14px;color:var(--green);
    border:1px solid var(--green);background:var(--green-d);border-radius:999px;
    padding:7px 14px;font-variant-numeric:tabular-nums;white-space:nowrap}
  .roi span{opacity:.5;margin:0 6px}

  .legs{padding:6px 16px}
  .leg{display:grid;grid-template-columns:150px 1fr 110px 120px 64px;gap:14px;
    align-items:center;padding:12px 0;border-bottom:1px solid var(--line)}
  .leg:last-child{border-bottom:0}
  .book{display:flex;align-items:center;gap:9px;min-width:0}
  .chip{width:26px;height:26px;border-radius:7px;flex:none;display:grid;place-items:center;
    font-size:11px;font-weight:700;color:#fff;
    background:hsl(var(--h) 55% 42%)}
  .bk{font-size:13px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sel{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0}
  .pick{font-weight:500}
  .od{color:var(--blue);font-weight:700;font-variant-numeric:tabular-nums}
  .mkt{font-size:12px;color:var(--dim)}
  .first{font-size:11px;color:var(--blue);border:1px solid #284058;border-radius:999px;padding:2px 9px}
  .cell{display:flex;flex-direction:column;gap:2px;text-align:right;font-variant-numeric:tabular-nums}
  .cell .lbl{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
  .cell .val{font-weight:600;font-size:14px}
  .pay .val{color:var(--green)}
  .bet{background:transparent;border:1px solid var(--blue);color:var(--blue);
    border-radius:9px;padding:9px 0;font-weight:600;font-size:13px;cursor:pointer}
  .bet:hover{background:#10243f}
  .both{display:block;width:calc(100% - 32px);margin:0 16px 16px;
    background:#0f1521;border:1px dashed #2a3650;color:var(--dim);
    border-radius:10px;padding:11px;font-weight:600;cursor:pointer}
  .both:hover{color:var(--ink);border-color:var(--green)}

  .empty{color:var(--dim);text-align:center;padding:60px 0}
  .foot{color:var(--dim);font-size:12px;margin-top:26px;border-top:1px solid var(--line);
    padding-top:16px;line-height:1.6}
  .foot b{color:#c2cce0}
  @media(max-width:720px){
    .leg{grid-template-columns:1fr;gap:6px;text-align:left}
    .cell{flex-direction:row;justify-content:space-between;text-align:left}
    .bet{width:100%}
    .roi{font-size:12px}
  }
</style>

<div class="wrap">
  <div class="top">
    <div>
      <h1>Arbitrage <b>Board</b></h1>
      <p class="lead">Every sportsbook, exchange, and DFS site the API covers — scanned on
        moneyline / two-way markets for guaranteed-profit arbs. Kalshi rows are net of
        trading fees. Prices move fast; confirm before placing.</p>
    </div>
    <div class="stats">
      <div class="stat"><div class="n">{{COUNT}}</div><div class="k">Opportunities</div></div>
      <div class="stat"><div class="n">{{BOOKS}}</div><div class="k">Books seen</div></div>
      <div class="stat"><div class="n">{{REMAINING}}</div><div class="k">API credits left</div></div>
    </div>
  </div>

  <div class="filters">
    <button class="on" data-f="all">All</button>
    <button data-f="odds">Sportsbooks &amp; exchanges</button>
    <button data-f="kalshi">Kalshi (net of fees)</button>
  </div>

  {{CARDS}}

  <p class="foot">Generated <b>{{GENERATED}}</b>. Snapshot — not live. Moneyline / two-way only
    (player props like the ones in pro tools need the per-event props endpoints, not yet wired).
    Re-run <b>python generate_report.py</b> to refresh.</p>
</div>

<script>
  const btns=[...document.querySelectorAll('.filters button')];
  btns.forEach(b=>b.onclick=()=>{
    btns.forEach(x=>x.classList.toggle('on',x===b));
    const f=b.dataset.f;
    document.querySelectorAll('.card').forEach(c=>{
      c.style.display=(f==='all'||c.dataset.src===f)?'':'none';
    });
  });
</script>
"""


def main():
    print("Scanning every sportsbook (all regions) + Kalshi ...")
    odds_opps, remaining = scan_odds_api()
    kalshi_opps = scan_kalshi()
    opps = odds_opps + kalshi_opps

    books = set()
    for o in odds_opps:
        for l in o["legs"]:
            books.add(l["book"])
    meta = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "remaining": remaining or "?",
        "books": len(books) + (1 if kalshi_opps else 0),
        "count": len(opps),
    }
    out = render(opps, meta)
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(out)
    print(f"  odds-api arbs: {len(odds_opps)} | kalshi arbs: {len(kalshi_opps)}")
    print(f"  wrote report.html ({len(opps)} cards). credits left: {remaining}")


if __name__ == "__main__":
    main()
