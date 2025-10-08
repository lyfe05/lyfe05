import requests
import re
import json
import unicodedata
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import pytz
from rapidfuzz import fuzz
import cloudscraper

# ---------- CONFIG ----------
LOCAL_TZ = pytz.timezone("Africa/Nairobi")

# ---------- FILTER RULES ----------
def load_banned_tournaments(filepath="banned.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tournaments = {line.strip().lower() for line in f if line.strip()}
        print(f"✅ Loaded {len(tournaments)} banned tournaments")
        return tournaments
    except FileNotFoundError:
        print(f"⚠️ banned.txt not found, continuing with empty ban list")
        return set()

BANNED_TOURNAMENTS_LOWER = load_banned_tournaments()

def is_banned_match(home: str, away: str, competition: str) -> bool:
    lname = (competition or "").strip().lower()
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
    if set(t1.split()) & set(t2.split()):
        return True
    if fuzz.ratio(t1, t2) >= 80 or fuzz.partial_ratio(t1, t2) >= 80:
        return True
    return t1 in t2 or t2 in t1

def teams_match(h1, a1, h2, a2):
    return names_equivalent(h1, h2) and names_equivalent(a1, a2)

# ---------- ONEFOOTBALL ----------
def fetch_onefootball_matches():
    print("\n[1️⃣] Fetching OneFootball matches...")
    url = "https://onefootball.com/en/matches"
    headers = {'User-Agent': 'Mozilla/5.0'}
    matches = []
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        print(f"   ✅ Status: {response.status_code}, Length: {len(response.text)}")
        json_pattern = r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>'
        match = re.search(json_pattern, response.text, re.DOTALL)
        if not match:
            print("   ⚠️ No JSON found in OneFootball response")
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

                    match_id = m.get("matchId") or m.get("trackingEvents", [{}])[0].get("typedServerParameter", {}).get("match_id", {}).get("value", "")
                    home_team = m.get("homeTeam", {}).get("name", "Unknown")
                    away_team = m.get("awayTeam", {}).get("name", "Unknown")
                    home_logo = m.get("homeTeam", {}).get("imageObject", {}).get("path", "No logo")
                    away_logo = m.get("awayTeam", {}).get("imageObject", {}).get("path", "No logo")
                    # keep scores if present
                    home_score = str(m.get("homeTeam", {}).get("score") or "0")
                    away_score = str(m.get("awayTeam", {}).get("score") or "0")

                    kickoff_utc = datetime.strptime(m["kickoff"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
                    kickoff_local = kickoff_utc.astimezone(LOCAL_TZ)
                    kickoff_str = kickoff_local.strftime("%Y-%m-%d %H:%M")

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
        print(f"   ✅ Parsed OneFootball matches: {len(matches)}")
    except Exception as e:
        print(f"   ⚠️ Error fetching OneFootball: {e}")
    return matches

# ---------- WHERESTHEMATCH ----------
def fetch_wheresthematch_matches():
    print("\n[2️⃣] Fetching WherestheMatch matches...")
    url = "https://www.wheresthematch.com/football-today/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    matches = []
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"   ✅ Status: {response.status_code}, Length: {len(response.text)}")
    except requests.RequestException as e:
        print(f"   ⚠️ Error fetching WherestheMatch: {e}")
        return matches
    soup = BeautifulSoup(response.text, 'html.parser')
    for row in soup.find_all('tr'):
        fixture_cell = row.find('td', class_='fixture-details')
        time_cell = row.find('td', class_='start-details')
        channels_cell = row.find('td', class_='channel-details')
        if not fixture_cell or not time_cell:
            continue
        team_links = fixture_cell.find_all('a')
        if len(team_links) < 2:
            continue
        home_team = team_links[0].get_text(strip=True)
        away_team = team_links[1].get_text(strip=True)
        comp_span = fixture_cell.find('span', class_='fixture-comp')
        competition = comp_span.get_text(" ", strip=True) if comp_span else "Unknown competition"
        time_span = time_cell.find('span', class_='time')
        kickoff_str = "Unknown"
        if time_span:
            try:
                uk_tz = pytz.timezone('Europe/London')
                raw_time = datetime.strptime(f"{datetime.today().date()} {time_span.get_text(strip=True)}", "%Y-%m-%d %H:%M")
                kickoff_local = uk_tz.localize(raw_time).astimezone(LOCAL_TZ)
                kickoff_str = kickoff_local.strftime("%Y-%m-%d %H:%M")
            except Exception:
                kickoff_str = "Unknown"
        channels = [img.get('title', 'Unknown Channel') for img in channels_cell.find_all('img', class_='channel')] if channels_cell else []
        if not channels:
            channels = ["Not specified"]
        matches.append({
            "home": home_team,
            "away": away_team,
            "competition": competition,
            "kickoff": kickoff_str,
            "channels": channels
        })
    print(f"   ✅ Parsed WherestheMatch matches: {len(matches)}")
    return matches

# ---------- DADDYLIVE ----------
def fetch_daddylive_matches():
    print("\n[3️⃣] Fetching DaddyLive matches...")
    url = "https://daddylivestream.com/schedule/schedule-generated.php"
    headers = {"User-Agent": "Mozilla/5.0","Referer": "https://daddylivestream.com/","Origin": "https://daddylivestream.com"}
    matches = []
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        schedule = response.json()
        for _, categories in schedule.items():
            for key, events in categories.items():
                if "soccer" not in key.lower():
                    continue
                for event in events:
                    event_name = event.get("event", "")
                    if "vs" not in event_name.lower():
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
                    # preserve original behavior: try to extract channel_name from dicts, otherwise keep string
                    ch1 = []
                    for c in event.get("channels", []) if event.get("channels") else []:
                        try:
                            if isinstance(c, dict):
                                ch1.append(c.get("channel_name", str(c)))
                            else:
                                ch1.append(str(c))
                        except Exception:
                            ch1.append(str(c))
                    ch2 = []
                    for c in event.get("channels2", []) if event.get("channels2") else []:
                        try:
                            if isinstance(c, dict):
                                ch2.append(c.get("channel_name", str(c)))
                            else:
                                ch2.append(str(c))
                        except Exception:
                            ch2.append(str(c))
                    matches.append({
                        "home": home,
                        "away": away,
                        "competition": comp,
                        "channels": ch1 + ch2 if (ch1 or ch2) else []
                    })
        print(f"   ✅ Parsed DaddyLive matches: {len(matches)}")
    except Exception as e:
        print(f"   ⚠️ Error fetching DaddyLive: {e}")
    return matches

# ---------- ALLFOOTBALL ----------
def fetch_allfootball_matches():
    print("\n[4️⃣] Fetching AllFootball matches...")
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
            print("   ⚠️ matchListStore not found.")
            return matches
        snippet = text[idx:]
        end_idx = snippet.find('}</script>')
        if end_idx != -1:
            snippet = snippet[:end_idx+1]
        snippet = "{" + snippet
        data = json.loads(snippet)
        raw_matches = data.get("matchListStore", {}).get("currentListData", [])
        today_local = datetime.now(LOCAL_TZ).date()
        for m in raw_matches:
            try:
                dt_str = f"{m.get('date_utc','')} {m.get('time_utc','00:00:00')}"
                match_utc = pytz.utc.localize(datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S"))
                match_local = match_utc.astimezone(LOCAL_TZ)
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
            except Exception:
                continue
        print(f"   ✅ Parsed AllFootball matches: {len(matches)}")
    except Exception as e:
        print(f"   ⚠️ Error fetching AllFootball: {e}")
    return matches

# ---------- MERGE ----------
def merge_matches():
    print("\n🚀 Running merge process...")
    onefootball = fetch_onefootball_matches()
    wtm = fetch_wheresthematch_matches()
    daddylive = fetch_daddylive_matches()
    allfootball = fetch_allfootball_matches()

    merged = []
    allowed_tournaments = set()
    print("\n🔍 Building allowed tournaments list...")
    for om in onefootball:
        if is_banned_match(om["home"], om["away"], om["competition"]):
            continue
        if any(teams_match(om["home"], om["away"], wm["home"], wm["away"]) for wm in wtm) or \
           any(teams_match(om["home"], om["away"], am["home"], am["away"]) for am in allfootball):
            allowed_tournaments.add(om["competition"].lower())
    print(f"   ✅ Allowed tournaments: {len(allowed_tournaments)}")

    print("\n📊 Merging matches...")
    for om in onefootball:
        if is_banned_match(om["home"], om["away"], om["competition"]):
            continue
        channels = []
        if any(teams_match(om["home"], om["away"], wm["home"], wm["away"]) for wm in wtm) or \
           any(teams_match(om["home"], om["away"], am["home"], am["away"]) for am in allfootball) or \
           om["competition"].lower() in allowed_tournaments:
            for dm in daddylive:
                if teams_match(om["home"], om["away"], dm["home"], dm["away"]):
                    channels.extend(dm.get("channels", []))
        if not channels:
            continue
        seen, clean_channels = set(), []
        for ch in channels:
            key = (ch or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                clean_channels.append(ch)
        merged.append({**om, "channels": clean_channels})

    merged.sort(key=lambda m: datetime.strptime(m["kickoff"], "%Y-%m-%d %H:%M") if m["kickoff"] != "Unknown" else datetime.max)

    print(f"\n✅ Final merged matches: {len(merged)}")

    # Print to console (workflow logs) using your requested multi-line format,
    # and also build a clean text representation to write to matches.txt
    lines_for_file = []
    for m in merged:
        # Multi-line console output (exact format you wanted)
        print(f"🏟️ Match: {m['home']} Vs {m['away']}")
        print(f"🆔 Match ID: {m.get('match_id', 'N/A')}")
        print(f"🕒 Start: {m['kickoff']} (GMT+3)")
        print(f"📍 Tournament: {m['competition']}")
        print(f"📺 Channels: {', '.join(m['channels']) if m['channels'] else 'Not specified'}")
        print(f"🖼️ Home Logo: {m.get('home_logo', 'N/A')}")
        print(f"🖼️ Away Logo: {m.get('away_logo', 'N/A')}")
        print("-" * 50)

        # Clean single-line for matches.txt
        channels_str = ', '.join(m['channels']) if m['channels'] else 'Not specified'
        file_line = f"{m['home']} vs {m['away']} - {m['kickoff']} (GMT+3) - {m['competition']} - Channels: {channels_str}"
        lines_for_file.append(file_line)

    # Write matches.txt (clean lines)
    try:
        with open("matches.txt", "w", encoding="utf-8") as f:
            for ln in lines_for_file:
                f.write(ln + "\n")
        print("\n📁 matches.txt written successfully.")
    except Exception as e:
        print(f"\n⚠️ Error writing matches.txt: {e}")

if __name__ == "__main__":
    merge_matches()
