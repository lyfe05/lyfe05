import requests
import re
import json
import unicodedata
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import pytz
from rapidfuzz import fuzz
import cloudscraper

# ---------- FILTER RULES ----------
def load_banned_tournaments(filepath="banned.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tournaments = {line.strip().lower() for line in f if line.strip()}
        return tournaments
    except FileNotFoundError:
        print(f"⚠️ banned.txt not found, continuing with empty ban list")
        return set()

BANNED_TOURNAMENTS_LOWER = load_banned_tournaments()

def is_banned_match(home: str, away: str, competition: str) -> bool:
    if not competition:
        competition = ""
    lname = competition.strip().lower()

    # exact banned competitions
    if lname in BANNED_TOURNAMENTS_LOWER:
        return True

    # forbidden terms in competition
    if "women" in lname or "nwsl" in lname:
        return True

    # youth/reserve patterns
    youth_patterns = ["u18", "u19", "u21", "u23", "youth", "reserve", "reserves", "academy"]
    if any(p in lname for p in youth_patterns):
        return True

    # team name checks
    if "women" in home.lower() or "women" in away.lower():
        return True
    if any(p in home.lower() for p in youth_patterns) or any(p in away.lower() for p in youth_patterns):
        return True

    return False

# ---------- HELPERS ----------
def normalize_team_name(name: str) -> str:
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("utf-8").lower()
    n = re.sub(r"[^a-z ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    stopwords = {"fc", "cf", "club", "the", "team", "deportivo"}
    tokens = [t for t in n.split() if t not in stopwords]
    return " ".join(tokens)

def names_equivalent(n1, n2):
    t1, t2 = normalize_team_name(n1), normalize_team_name(n2)
    if not t1 or not t2:
        return False
    s1, s2 = set(t1.split()), set(t2.split())
    if s1 & s2:
        return True
    if fuzz.ratio(t1, t2) >= 80:
        return True
    if fuzz.partial_ratio(t1, t2) >= 80:
        return True
    if t1 in t2 or t2 in t1:
        return True
    return False

def teams_match(h1, a1, h2, a2):
    return names_equivalent(h1, h2) and names_equivalent(a1, a2)

# ---------- ONEFOOTBALL ----------
def fetch_onefootball_matches():
    url = "https://onefootball.com/en/matches"
    headers = {'User-Agent': 'Mozilla/5.0'}
    matches = []
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        json_pattern = r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>'
        match = re.search(json_pattern, response.text, re.DOTALL)
        if not match:
            return matches
        json_data = json.loads(match.group(1))
        containers = json_data.get("props", {}).get("pageProps", {}).get("containers", [])
        for container in containers:
            comp = container.get("type", {}).get("fullWidth", {}).get("component", {})
            if comp.get("contentType", {}).get("$case") == "matchCardsList":
                for m in comp["contentType"]["matchCardsList"]["matchCards"]:
                    try:
                        competition = m.get("trackingEvents", [None])[0].get("typedServerParameter", {}).get("competition", {}).get("value", "Unknown Tournament")
                    except Exception:
                        competition = "Unknown Tournament"
                    
                    # ✅ Extract match_id (try both ways)
                    match_id = m.get("matchId") or m.get("trackingEvents", [{}])[0].get("typedServerParameter", {}).get("match_id", {}).get("value", "")

                    home_team = m.get("homeTeam", {}).get("name", "Unknown")
                    away_team = m.get("awayTeam", {}).get("name", "Unknown")
                    home_logo = m.get("homeTeam", {}).get("imageObject", {}).get("path", "No logo")
                    away_logo = m.get("awayTeam", {}).get("imageObject", {}).get("path", "No logo")
                    home_score = str(m.get("homeTeam", {}).get("score") or "0")
                    away_score = str(m.get("awayTeam", {}).get("score") or "0")
                    kickoff_utc = datetime.strptime(m["kickoff"], "%Y-%m-%dT%H:%M:%SZ")
                    kickoff_gmt3 = kickoff_utc + timedelta(hours=3)
                    kickoff_str = kickoff_gmt3.strftime("%Y-%m-%d %H:%M")
                    
                    matches.append({
                        "match_id": match_id,
                        "home": home_team,
                        "away": away_team,
                        "competition": competition,
                        "kickoff": kickoff_str,
                        "home_logo": home_logo,
                        "away_logo": away_logo,
                        "home_score": home_score,
                        "away_score": away_score
                    })
    except Exception as e:
        print(f"⚠️ Error fetching OneFootball: {e}")
    return matches

# (other fetch_... functions remain unchanged)

# ---------- MERGE ----------
def merge_matches():
    onefootball = fetch_onefootball_matches()
    wtm = fetch_wheresthematch_matches()
    daddylive = fetch_daddylive_matches()
    allfootball = fetch_allfootball_matches()
    merged = []

    allowed_tournaments = set()
    for om in onefootball:
        if is_banned_match(om.get("home",""), om.get("away",""), om.get("competition","")):
            continue
        wtm_matches = [wm for wm in wtm if teams_match(om["home"], om["away"], wm["home"], wm["away"])]
        af_matches = [am for am in allfootball if teams_match(om["home"], om["away"], am["home"], am["away"])]
        if wtm_matches or af_matches:
            allowed_tournaments.add(om["competition"].lower())

    for om in onefootball:
        if is_banned_match(om.get("home",""), om.get("away",""), om.get("competition","")):
            continue

        wtm_matches = [wm for wm in wtm if teams_match(om["home"], om["away"], wm["home"], wm["away"])]
        af_matches = [am for am in allfootball if teams_match(om["home"], om["away"], am["home"], am["away"])]
        channels = []

        if wtm_matches:
            for wm in wtm_matches:
                channels.extend(wm.get("channels", []))
            for dm in daddylive:
                if teams_match(om["home"], om["away"], dm["home"], dm["away"]):
                    channels.extend(dm.get("channels", []))
        elif af_matches:
            for dm in daddylive:
                if teams_match(om["home"], om["away"], dm["home"], dm["away"]):
                    channels.extend(dm.get("channels", []))
        elif om["competition"].lower() in allowed_tournaments:
            for dm in daddylive:
                if teams_match(om["home"], om["away"], dm["home"], dm["away"]):
                    channels.extend(dm.get("channels", []))
        else:
            continue

        seen, clean_channels = set(), []
        for ch in channels:
            key = (ch or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                clean_channels.append(ch)

        merged.append({**om, "channels": clean_channels})

    def kickoff_key(match):
        try:
            return datetime.strptime(match["kickoff"], "%Y-%m-%d %H:%M")
        except Exception:
            return datetime.max
    merged.sort(key=kickoff_key)

    # ✅ Now we also print match_id
    for m in merged:
        print(f"🏟️ Match: {m['home']} Vs {m['away']}")
        print(f"🆔 Match ID: {m.get('match_id', 'N/A')}")
        print(f"🕒 Start: {m['kickoff']} (GMT+3)")
        print(f"📍 Tournament: {m['competition']}")
        print(f"📺 Channels: {', '.join(m['channels']) if m['channels'] else 'Not specified'}")
        print(f"🖼️ Home Logo: {m.get('home_logo', 'N/A')}")
        print(f"🖼️ Away Logo: {m.get('away_logo', 'N/A')}")
        print(f"⚽ Score: {m.get('home_score', '0')} | {m.get('away_score', '0')}")
        print("-" * 50)

if __name__ == "__main__":
    merge_matches()
