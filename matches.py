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

    if lname in BANNED_TOURNAMENTS_LOWER:
        return True

    if "women" in lname or "nwsl" in lname:
        return True

    youth_patterns = ["u18", "u19", "u21", "u23", "youth", "reserve", "reserves", "academy"]
    if any(p in lname for p in youth_patterns):
        return True

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
    print("🔍 Fetching matches from OneFootball...")
    url = "https://onefootball.com/en/matches"
    headers = {'User-Agent': 'Mozilla/5.0'}
    matches = []
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        json_pattern = r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>'
        match = re.search(json_pattern, response.text, re.DOTALL)
        if not match:
            print("❌ No JSON data found in OneFootball response")
            return matches
        json_data = json.loads(match.group(1))
        containers = json_data.get("props", {}).get("pageProps", {}).get("containers", [])
        print(f"📊 Found {len(containers)} containers in OneFootball")
        
        match_count = 0
        for container in containers:
            comp = container.get("type", {}).get("fullWidth", {}).get("component", {})
            if comp.get("contentType", {}).get("$case") == "matchCardsList":
                match_cards = comp["contentType"]["matchCardsList"]["matchCards"]
                match_count += len(match_cards)
                for m in match_cards:
                    try:
                        competition = m.get("trackingEvents", [None])[0].get("typedServerParameter", {}).get("competition", {}).get("value", "Unknown Tournament")
                    except Exception:
                        competition = "Unknown Tournament"

                    # ✅ Extract match ID (try two sources)
                    match_id = m.get("matchId") or m.get("trackingEvents", [{}])[0].get("typedServerParameter", {}).get("match_id", {}).get("value", "")

                    home_team = m.get("homeTeam", {}).get("name", "Unknown")
                    away_team = m.get("awayTeam", {}).get("name", "Unknown")
                    home_logo = m.get("homeTeam", {}).get("imageObject", {}).get("path", "No logo")
                    away_logo = m.get("awayTeam", {}).get("imageObject", {}).get("path", "No logo")
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
                        "away_logo": away_logo
                    })
        print(f"✅ OneFootball: Found {len(matches)} matches")
    except Exception as e:
        print(f"❌ Error fetching OneFootball: {e}")
    return matches

# ---------- WHERESTHEMATCH ----------
def fetch_wheresthematch_matches():
    print("🔍 Fetching matches from WherestheMatch...")
    url = "https://www.wheresthematch.com/football-today/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    matches = []
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Error fetching WherestheMatch: {e}")
        return matches
    soup = BeautifulSoup(response.text, 'html.parser')
    rows = soup.find_all('tr')
    print(f"📊 Found {len(rows)} rows in WherestheMatch")
    
    match_count = 0
    for row in rows:
        fixture_cell = row.find('td', class_='fixture-details')
        time_cell = row.find('td', class_='start-details')
        channels_cell = row.find('td', class_='channel-details')
        if not fixture_cell or not time_cell:
            continue
        team_links = fixture_cell.find_all('a')
        if len(team_links) >= 2:
            home_team = team_links[0].get_text(strip=True)
            away_team = team_links[1].get_text(strip=True)
        else:
            continue
        comp_span = fixture_cell.find('span', class_='fixture-comp')
        competition = comp_span.get_text(" ", strip=True) if comp_span else "Unknown competition"
        time_span = time_cell.find('span', class_='time')
        kickoff_str = "Unknown"
        if time_span:
            try:
                bst = pytz.timezone('Europe/London')
                eat = pytz.timezone('Africa/Nairobi')
                bst_time = bst.localize(datetime.strptime(f"{datetime.today().date()} {time_span.get_text(strip=True)}", "%Y-%m-%d %H:%M"))
                kickoff_str = bst_time.astimezone(eat).strftime("%Y-%m-%d %H:%M")
            except Exception:
                kickoff_str = "Unknown"
        channels = []
        if channels_cell:
            channels = [img.get('title', 'Unknown Channel') for img in channels_cell.find_all('img', class_='channel')]
        if not channels:
            channels = ["Not specified"]
        matches.append({
            "home": home_team,
            "away": away_team,
            "competition": competition,
            "kickoff": kickoff_str,
            "channels": channels
        })
        match_count += 1
    
    print(f"✅ WherestheMatch: Found {len(matches)} matches")
    return matches

# ---------- DADDYLIVE ----------
def fetch_daddylive_matches():
    print("🔍 Fetching matches from DaddyLive...")
    url = "https://daddylivestream.com/schedule/schedule-generated.php"
    headers = {"User-Agent": "Mozilla/5.0","Referer": "https://daddylivestream.com/","Origin": "https://daddylivestream.com"}
    matches = []
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        schedule = response.json()
        print(f"📊 DaddyLive: Processing {len(schedule)} categories")
        
        match_count = 0
        for _, categories in schedule.items():
            for key, events in categories.items():
                if "soccer" not in key.lower():
                    continue
                print(f"📋 Processing soccer category: {key} with {len(events)} events")
                for event in events:
                    event_name = event.get("event", "")
                    if " : " not in event_name or "vs" not in event_name.lower():
                        continue
                    try:
                        comp, fixture = event_name.split(":", 1)
                        comp = comp.strip()
                    except ValueError:
                        comp, fixture = "Unknown Competition", event_name
                    parts = re.split(r"\s+vs\.?\s+", fixture, flags=re.IGNORECASE)
                    if len(parts) != 2:
                        continue
                    home, away = [p.strip() for p in parts]

                    def extract_channels(ch_list):
                        result = []
                        for c in ch_list:
                            if isinstance(c, dict):
                                result.append(c.get("channel_name", "Unknown"))
                            elif isinstance(c, str):
                                result.append(c)
                        return result

                    ch1 = extract_channels(event.get("channels", []))
                    ch2 = extract_channels(event.get("channels2", []))
                    matches.append({
                        "home": home,
                        "away": away,
                        "competition": comp,
                        "channels": ch1 + ch2 if (ch1 or ch2) else []
                    })
                    match_count += 1
        print(f"✅ DaddyLive: Found {len(matches)} matches")
    except Exception as e:
        print(f"❌ Error fetching DaddyLive: {e}")
    return matches

# ---------- ALLFOOTBALL ----------
def fetch_allfootball_matches():
    print("🔍 Fetching matches from AllFootball...")
    url = "https://m.allfootballapp.com/matchs"
    headers = {"User-Agent": "Mozilla/5.0"}
    matches = []
    scraper = cloudscraper.create_scraper()
    try:
        resp = scraper.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        text = resp.text
        idx = text.find('"matchListStore":')
        if idx == -1:
            print("❌ No matchListStore found in AllFootball response")
            return matches
        snippet = text[idx:]
        end_idx = snippet.find('}</script>')
        if end_idx != -1:
            snippet = snippet[:end_idx+1]
        snippet = "{" + snippet
        data = json.loads(snippet)
        raw_matches = data.get("matchListStore", {}).get("currentListData", [])
        print(f"📊 AllFootball: Found {len(raw_matches)} raw matches")
        
        local_tz = pytz.timezone("Africa/Nairobi")
        today_local = datetime.now(local_tz).date()
        match_count = 0
        for m in raw_matches:
            try:
                dt_str = f"{m.get('date_utc','')} {m.get('time_utc','00:00:00')}"
                match_utc = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                match_utc = pytz.utc.localize(match_utc)
                match_local = match_utc.astimezone(local_tz)
                if match_local.date() != today_local:
                    continue
                kickoff_str = match_local.strftime("%Y-%m-%d %H:%M")
                matches.append({
                    "home": m.get("team_A_name", "Unknown"),
                    "away": m.get("team_B_name", "Unknown"),
                    "competition": m.get("competition_name", "Unknown Tournament"),
                    "kickoff": kickoff_str,
                    "home_logo": m.get("team_A_logo", "No logo"),
                    "away_logo": m.get("team_B_logo", "No logo")
                })
                match_count += 1
            except Exception:
                continue
        print(f"✅ AllFootball: Found {len(matches)} matches for today")
    except Exception as e:
        print(f"❌ Error fetching AllFootball: {e}")
    return matches

# ---------- MERGE ----------
def merge_matches():
    print("🚀 Starting match aggregation process...")
    print("=" * 50)
    
    onefootball = fetch_onefootball_matches()
    print("-" * 30)
    
    wtm = fetch_wheresthematch_matches()
    print("-" * 30)
    
    daddylive = fetch_daddylive_matches()
    print("-" * 30)
    
    allfootball = fetch_allfootball_matches()
    print("-" * 30)
    
    print("🔄 Merging matches from all sources...")
    merged = []

    # ---------- FIRST PASS: build allowed tournaments ----------
    print("📋 Building allowed tournaments list...")
    allowed_tournaments = set()
    banned_count = 0
    
    for om in onefootball:
        if is_banned_match(om.get("home",""), om.get("away",""), om.get("competition","")):
            banned_count += 1
            continue

        wtm_matches = [wm for wm in wtm if teams_match(om["home"], om["away"], wm["home"], wm["away"])]
        af_matches = [am for am in allfootball if teams_match(om["home"], om["away"], am["home"], am["away"])]

        if wtm_matches or af_matches:
            allowed_tournaments.add(om["competition"].lower())

    print(f"✅ Allowed tournaments: {len(allowed_tournaments)}")
    print(f"❌ Banned matches filtered: {banned_count}")

    # ---------- SECOND PASS: build final matches ----------
    print("🎯 Building final match list...")
    merged_count = 0
    
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
        merged_count += 1

    def kickoff_key(match):
        try:
            return datetime.strptime(match["kickoff"], "%Y-%m-%d %H:%M")
        except Exception:
            return datetime.max
    merged.sort(key=kickoff_key)

    print("=" * 50)
    print(f"🎉 FINAL RESULTS: {len(merged)} matches found")
    print("=" * 50)

    for m in merged:
        print(f"🏟️ Match: {m['home']} Vs {m['away']}")
        print(f"🆔 Match ID: {m.get('match_id', 'N/A')}")
        print(f"🕒 Start: {m['kickoff']} (GMT+3)")
        print(f"📍 Tournament: {m['competition']}")
        print(f"📺 Channels: {', '.join(m['channels']) if m['channels'] else 'Not specified'}")
        print(f"🖼️ Home Logo: {m.get('home_logo', 'N/A')}")
        print(f"🖼️ Away Logo: {m.get('away_logo', 'N/A')}")
        print("-" * 50)

    print(f"✅ Process completed! Total matches: {len(merged)}")

if __name__ == "__main__":
    merge_matches()
