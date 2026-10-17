#!/usr/bin/env python3
"""
Builds site/data.json for the CHP college basketball wins pool.

  python build.py                      # fetch live scores from Massey (normal use)
  python build.py --file saved.html    # use a saved copy of the Massey page instead
  python build.py --today 2026-01-20   # pretend it's a different day (for testing)

Uses only the Python standard library, so there is nothing to install.
League setup lives in the league/ folder; see README.md.
"""
import argparse
import bisect
import csv
import datetime as dt
import difflib
import html
import json
import re
import sys
import time
import tomllib
import urllib.request
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
LEAGUE = ROOT / "league"
SITE = ROOT / "site"


# ---------------------------------------------------------------- inputs

def read_csv(name):
    path = LEAGUE / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items() if k}
                for row in csv.DictReader(f)]


def load_settings():
    with open(LEAGUE / "settings.toml", "rb") as f:
        s = tomllib.load(f)
    s.setdefault("weekly_prizes", [35, 25, 15, 10])
    s.setdefault("tie_rule", "pct")
    s.setdefault("timezone", "America/New_York")
    return s


def fetch_scores(url, attempts=3):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (CHP pool standings; runs a few times a day)"})
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # network hiccup: wait and retry
            last = e
            time.sleep(10 * (i + 1))
    raise SystemExit(f"Could not download scores from {url}: {last}")


DATE_RE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{8})"
LINE_RE = re.compile(r"^\s*" + DATE_RE + r"\s+(.+?)\s+(\d+)\s+(.+?)\s+(\d+)(?:\s+(.*))?$")


def parse_date(s):
    if "-" in s:
        return dt.date.fromisoformat(s)
    if "/" in s:
        m, d, y = s.split("/")
        return dt.date(int(y), int(m), int(d))
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))


def clean_team(s):
    return s.replace("@", "").strip()


def parse_games(text):
    """Turn Massey's plain-text scores listing into a list of games."""
    pre = re.findall(r"<pre[^>]*>(.*?)</pre>", text, flags=re.S | re.I)
    body = "\n".join(pre) if pre else text
    body = html.unescape(re.sub(r"<[^>]+>", "", body))
    games = []
    for line in body.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        d, t1, s1, t2, s2, note = m.groups()
        s1, s2 = int(s1), int(s2)
        if s1 == 0 and s2 == 0:          # scheduled, not played yet
            continue
        w, l, ws, ls = clean_team(t1), clean_team(t2), s1, s2
        if ls > ws:                       # Massey lists the winner first; just in case
            w, l, ws, ls = l, w, ls, ws
        games.append({"date": parse_date(d), "winner": w, "loser": l,
                      "ws": ws, "ls": ls, "note": (note or "").strip()})
    return games


# ---------------------------------------------------------------- helpers

def pct(w, l):
    return Fraction(w, w + l) if (w + l) else Fraction(0)


def rank(rows, tie_rule):
    """rows: list of dicts with W and L. Sorts best-first and adds rank labels.
    Ties are never broken: tied players share a place, shown as '2-T'."""
    def key(r):
        return (pct(r["W"], r["L"]), r["W"])
    rows.sort(key=lambda r: (-key(r)[0], -key(r)[1], r["name"]))

    def same(a, b):
        if tie_rule == "record":
            return a["W"] == b["W"] and a["L"] == b["L"]
        return pct(a["W"], a["L"]) == pct(b["W"], b["L"])

    i = 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and same(rows[i], rows[j]):
            j += 1
        size = j - i
        for r in rows[i:j]:
            r["place"] = i + 1
            r["tied"] = size
            r["rank"] = f"{i + 1}-T" if size > 1 else str(i + 1)
        i = j
    for r in rows:
        r["pct"] = round(float(pct(r["W"], r["L"])), 4)
    return rows


def split_prizes(ranked, prizes):
    """Tied players split the combined money for the places they occupy."""
    for r in ranked:
        r["prize"] = 0.0
    i = 0
    while i < len(ranked):
        size = ranked[i]["tied"]
        start = ranked[i]["place"] - 1
        pool = sum(prizes[k] for k in range(start, start + size) if k < len(prizes))
        for r in ranked[i:i + size]:
            r["prize"] = round(pool / size, 2)
        i += size
    return ranked


def worst_index(records):
    """The team that gets dropped: lowest win %, and with equal win % the one
    with more losses (same as the old spreadsheet)."""
    best, idx = None, 0
    for i, (w, l) in enumerate(records):
        k = (pct(w, l), -l)
        if best is None or k < best:
            best, idx = k, i
    return idx


# ---------------------------------------------------------------- Hebert Cup

def build_cup(settings, weeks, rosters, by_week, margin, warnings):
    """Plays out the Cup bracket from the first-round matchups in cup.csv.
    Winners meet in bracket order: winner of matchup 1 plays winner of 2, etc."""
    first = [(r["player1"], r["player2"]) for r in read_csv("cup.csv") if r.get("player1") or r.get("player2")]
    if not first:
        return {"rounds": [], "champion": None}
    overrides = {(r["week"], r["player"]) for r in read_csv("cup_overrides.csv") if r.get("week")}
    cup_weeks = [str(w) for w in settings.get("cup_weeks", ["2", "3", "4", "5", "6"])]
    by_id = {w["id"]: w for w in weeks}
    order = [w["id"] for w in weeks]
    for p in {x for m in first for x in m if x}:
        if p not in rosters:
            warnings.append(f"cup.csv: '{p}' isn't in the draft list.")

    def line(p, wk):
        """Everything the tiebreakers need for one player in one week."""
        half = by_id[wk]["half"]
        teams = [s[f"h{half}"] for s in rosters.get(p, [])]
        w = sum(by_week[(wk, t)][0] for t in teams)
        l = sum(by_week[(wk, t)][1] for t in teams)
        i = order.index(wk)
        prev = order[i - 1] if i > 0 else None
        pw = sum(by_week[(prev, t)][0] for t in teams) if prev else 0
        pl = sum(by_week[(prev, t)][1] for t in teams) if prev else 0
        picks = [pct(*by_week[(wk, t)]) for t in reversed(teams)]   # #10 pick first
        return {"W": w, "L": l, "pct": pct(w, l), "prev": pct(pw, pl),
                "pd": sum(margin[(wk, t)] for t in teams), "picks": picks}

    steps = [("record", "win %", lambda x: x["pct"]),
             ("wins", "more wins", lambda x: x["W"]),
             ("prev", "prior week win %", lambda x: x["prev"]),
             ("pd", "point differential", lambda x: x["pd"])]

    def decide(a, b, wk):
        la, lb = line(a, wk), line(b, wk)
        if (wk, a) in overrides or (wk, b) in overrides:
            return (a if (wk, a) in overrides else b), "commissioner", la, lb
        for _, label, f in steps:
            if f(la) != f(lb):
                return (a if f(la) > f(lb) else b), label, la, lb
        for n, (x, y) in enumerate(zip(la["picks"], lb["picks"])):
            if x != y:
                return (a if x > y else b), f"win % of #{10 - n} pick", la, lb
        return None, "tied on every tiebreaker", la, lb

    rounds, players = [], [x for m in first for x in m]
    for wk in cup_weeks:
        if wk not in by_id:
            warnings.append(f"settings.toml: cup week '{wk}' isn't in weeks.csv.")
            break
        w = by_id[wk]
        matches, nxt = [], []
        for a, b in zip(players[0::2], players[1::2]):
            m = {"p1": a, "p2": b, "winner": None, "how": ""}
            if a and b and w["status"] != "upcoming":
                win, how, la, lb = decide(a, b, wk)
                m["r1"], m["r2"] = [la["W"], la["L"]], [lb["W"], lb["L"]]
                if how != "win %":
                    m["detail"] = {"pd": [la["pd"], lb["pd"]], "prev": [float(la["prev"]), float(lb["prev"])]}
                if w["status"] == "final":
                    m["winner"], m["how"] = win, how
                    if win is None:
                        warnings.append(f"Cup {w['label']}: {a} vs {b} is tied on every tiebreaker. "
                                        f"Add the winner to league/cup_overrides.csv.")
                else:
                    m["leader"], m["how"] = win, how
            elif w["status"] == "final" and (a or b) and not (a and b):
                m["winner"], m["how"] = a or b, "bye"
            matches.append(m)
            nxt.append(m["winner"])
        rounds.append({"week": wk, "label": w["label"], "status": w["status"], "matches": matches})
        players = nxt
        if len(players) < 2:
            break
    champ = players[0] if len(players) == 1 else None
    return {"rounds": rounds, "champion": champ}


# ---------------------------------------------------------------- main build

def build(games, settings, today):
    tie_rule = settings["tie_rule"]
    prizes = settings["weekly_prizes"]
    warnings = []

    d1 = {t.strip() for t in (LEAGUE / "d1_teams.txt").read_text(encoding="utf-8").splitlines() if t.strip()}

    # Weeks
    wk_rows = read_csv("weeks.csv")
    weeks = []
    for r in wk_rows:
        weeks.append({"id": r["week"], "start": dt.date.fromisoformat(r["start_date"]),
                      "half": int(r["half"]), "prize": r.get("weekly_prize", "Y").upper().startswith("Y")})
    weeks.sort(key=lambda w: w["start"])
    starts = [w["start"] for w in weeks]
    for i, w in enumerate(weeks):
        nxt = weeks[i + 1]["start"] if i + 1 < len(weeks) else None
        w["end"] = (nxt - dt.timedelta(days=1)) if nxt else None
        if today < w["start"]:
            w["status"] = "upcoming"
        elif nxt is None or today < nxt:
            w["status"] = "live"
        else:
            w["status"] = "final"
        w["label"] = f"Week {w['id']}" if w["id"].isdigit() else w["id"]

    def week_of(d):
        i = bisect.bisect_right(starts, d) - 1
        return weeks[i] if i >= 0 else None

    # Draft
    draft = read_csv("draft.csv")
    players, rosters = [], defaultdict(list)
    for r in draft:
        p = r["player"]
        if p not in rosters:
            players.append(p)
        rosters[p].append({"pick": r.get("pick", ""), "h1": r["team"],
                           "h2": r.get("second_half_team") or r["team"]})
    owned = {t for p in players for s in rosters[p] for t in (s["h1"], s["h2"])}

    # Tally games: team records by half and by week
    by_half = defaultdict(lambda: [0, 0])     # (half, team) -> [W, L]
    by_week = defaultdict(lambda: [0, 0])     # (week id, team) -> [W, L]
    margin = defaultdict(int)                 # (week id, team) -> point differential
    seen_teams = set()
    owned_games = []
    for g in games:
        seen_teams.update((g["winner"], g["loser"]))
        wk = week_of(g["date"])
        if wk is None:                        # before week 1 (exhibitions)
            continue
        win_counts = g["loser"] in d1         # a win only counts against a D1 opponent
        if win_counts:
            by_half[(wk["half"], g["winner"])][0] += 1
            by_week[(wk["id"], g["winner"])][0] += 1
        by_half[(wk["half"], g["loser"])][1] += 1
        by_week[(wk["id"], g["loser"])][1] += 1
        margin[(wk["id"], g["winner"])] += g["ws"] - g["ls"]
        margin[(wk["id"], g["loser"])] -= g["ws"] - g["ls"]
        if g["winner"] in owned or g["loser"] in owned:
            owned_games.append([g["date"].isoformat(), wk["id"], g["winner"], g["ws"],
                                g["loser"], g["ls"], 1 if win_counts else 0])

    if games:
        for t in sorted(owned - seen_teams):
            close = difflib.get_close_matches(t, sorted(seen_teams), n=3, cutoff=0.6)
            warnings.append(f"No games found for drafted team '{t}'."
                            + (f" Did you mean: {', '.join(close)}?" if close else ""))

    # Player results
    out_players = []
    for p in players:
        slots = rosters[p]
        entry = {"name": p, "teams": [], "half": {}}
        for half in (1, 2):
            recs = [tuple(by_half[(half, s[f"h{half}"])]) for s in slots]
            drop = worst_index(recs)
            entry["half"][half] = {
                "W": sum(r[0] for i, r in enumerate(recs) if i != drop),
                "L": sum(r[1] for i, r in enumerate(recs) if i != drop),
                "dropped": slots[drop][f"h{half}"]}
            entry[f"drop{half}"] = drop
        for i, s in enumerate(slots):
            entry["teams"].append({
                "pick": s["pick"],
                "h1": {"team": s["h1"], "W": by_half[(1, s["h1"])][0], "L": by_half[(1, s["h1"])][1],
                       "dropped": i == entry["drop1"]},
                "h2": {"team": s["h2"], "W": by_half[(2, s["h2"])][0], "L": by_half[(2, s["h2"])][1],
                       "dropped": i == entry["drop2"], "redraft": s["h2"] != s["h1"]}})
        entry["weekly"] = {}
        for w in weeks:
            if w["status"] == "upcoming":
                continue
            ts = [s[f"h{w['half']}"] for s in slots]
            entry["weekly"][w["id"]] = [sum(by_week[(w["id"], t)][0] for t in ts),
                                        sum(by_week[(w["id"], t)][1] for t in ts)]
        out_players.append(entry)

    # Standings
    def table(fn):
        return rank([dict(name=e["name"], **fn(e)) for e in out_players], tie_rule)

    standings = {
        "season": table(lambda e: {"W": e["half"][1]["W"] + e["half"][2]["W"],
                                   "L": e["half"][1]["L"] + e["half"][2]["L"]}),
        "h1": table(lambda e: {"W": e["half"][1]["W"], "L": e["half"][1]["L"]}),
        "h2": table(lambda e: {"W": e["half"][2]["W"], "L": e["half"][2]["L"]}),
    }

    weekly = {}
    week_money = defaultdict(float)
    for w in weeks:
        if w["status"] == "upcoming":
            continue
        rows = table(lambda e: {"W": e["weekly"][w["id"]][0], "L": e["weekly"][w["id"]][1]})
        if w["prize"]:
            split_prizes(rows, prizes)
            if w["status"] == "final":
                for r in rows:
                    week_money[r["name"]] += r["prize"]
        weekly[w["id"]] = rows

    # Money: weekly prizes (automatic) + everything in payouts.csv (manual)
    items = defaultdict(list)
    for r in read_csv("payouts.csv"):
        try:
            amt = float(r["amount"])
        except ValueError:
            warnings.append(f"payouts.csv: '{r['amount']}' isn't a number ({r['player']}, {r['description']}).")
            continue
        if r["player"] not in rosters:
            warnings.append(f"payouts.csv: '{r['player']}' isn't in the draft list.")
        items[r["player"]].append({"category": r["category"], "description": r["description"], "amount": amt})
    money = []
    for p in players:
        prizes_won = sum(i["amount"] for i in items[p] if not i["category"].lower().startswith("credit"))
        credit = sum(i["amount"] for i in items[p] if i["category"].lower().startswith("credit"))
        money.append({"name": p, "weekly": round(week_money[p], 2), "prizes": round(prizes_won, 2),
                      "credit": round(credit, 2), "winnings": round(week_money[p] + prizes_won, 2),
                      "total": round(week_money[p] + prizes_won + credit, 2), "items": items[p]})

    # Team index: who owns each team
    teams = {}
    for e in out_players:
        for t in e["teams"]:
            for half in ("h1", "h2"):
                info = teams.setdefault(t[half]["team"], {"h1": [], "h2": [],
                                                          "rec1": by_half[(1, t[half]["team"])],
                                                          "rec2": by_half[(2, t[half]["team"])]})
                if e["name"] not in info[half]:
                    info[half].append(e["name"])

    cup = build_cup(settings, weeks, rosters, by_week, margin, warnings)

    live = [w for w in weeks if w["status"] != "upcoming"]
    current = live[-1]["id"] if live else (weeks[0]["id"] if weeks else None)
    last_game = max((g["date"] for g in games), default=None)

    for e in out_players:
        e.pop("drop1"), e.pop("drop2")

    rules = LEAGUE / "rules.md"
    return {
        "league": settings.get("league_name", "CHP"),
        "season": settings.get("season", ""),
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "last_game": last_game.isoformat() if last_game else None,
        "games_counted": sum(1 for g in games if week_of(g["date"])),
        "tie_rule": tie_rule,
        "weekly_prizes": prizes,
        "weeks": [{"id": w["id"], "label": w["label"], "start": w["start"].isoformat(),
                   "end": w["end"].isoformat() if w["end"] else None, "half": w["half"],
                   "prize": w["prize"], "status": w["status"]} for w in weeks],
        "current_week": current,
        "players": out_players,
        "standings": standings,
        "weekly": weekly,
        "money": money,
        "teams": teams,
        "games": owned_games,
        "cup": cup,
        "hall_of_fame": read_csv("hall_of_fame.csv"),
        "rules": rules.read_text(encoding="utf-8") if rules.exists() else "",
        "warnings": warnings,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="read a saved Massey page instead of downloading")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing")
    ap.add_argument("--out", default=str(SITE / "data.json"))
    a = ap.parse_args()

    settings = load_settings()
    text = Path(a.file).read_text(encoding="utf-8", errors="replace") if a.file \
        else fetch_scores(settings["massey_url"])
    games = parse_games(text)
    if not games:
        print("No games could be read from the Massey page. First 1,000 characters received:")
        print(text[:1000])
        sys.exit(1)

    tz = ZoneInfo(settings["timezone"])
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(tz).date()
    data = build(games, settings, today)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Read {len(games)} games ({data['games_counted']} in league weeks), "
          f"latest {data['last_game']}. Current week: {data['current_week']}.")
    lead = data["standings"]["season"][0]
    print(f"Season leader: {lead['name']} {lead['W']}-{lead['L']}")
    for w in data["warnings"]:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
