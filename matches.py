import requests
import re
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import pytz
from rapidfuzz import fuzz
import cloudscraper
import logging

# ---------- HELPERS ----------
def normalize_team_name(name):
    return re.sub(r'[^a-z0-9]', '', str(name).lower())

def fuzzy_match(name1, name2, threshold=85):
    return fuzz.ratio(normalize_team_name(name1), normalize_team_name(name2)) >= threshold

def teams_match(h1, a1, h2, a2):
    """Check if two fixtures are the same using exact, partial, or fuzzy matching"""
    if normalize_team_name(h1) == normalize_team_name(h2) and normalize_team_name(a1) == normalize_team_name(a2):
        return True
    if (normalize_team_name(h1) == normalize_team_name(h2) or 
        normalize_team_name(a1) == normalize_team_name(a2)):
        return True
    if fuzzy_match(h1, h2) and fuzzy_match(a1, a2):
        return True
    return False

# ---------- ONEFOOTBALL ----------
def fetch_onefootball_matches():
    url = "https://onefootball.com/en/matches"
    headers = {'User-Agent': 'Mozilla/5.0 (Android; Mobile; rv:109.0) Gecko/109.0 Firefox/109.0'}
    matches = []

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        json_pattern = r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>'
        match = re.search(json_pattern, response.text, re.DOTALL)
        if not match:
            return matches

        json_data = json.loads(match.group(1))
        containers = json_data["props"]["pageProps"]["containers"]

        for container in containers:
            comp = container["type"].get("fullWidth", {}).get("component", {})
            if comp.get("contentType", {}).get("$case") == "matchCardsList":
                for m in comp["contentType"]["matchCardsList"]["matchCards"]:
                    try:
                        competition = m["trackingEvents"][0]["typedServerParameter"]["competition"]["value"]
                    except:
                        competition = "Unknown Tournament"

                    home_team = m["homeTeam"]["name"]
                    away_team = m["awayTeam"]["name"]
                    home_logo = m["homeTeam"]["imageObject"]["path"]
                    away_logo = m["awayTeam"]["imageObject"]["path"]

                    home_score = m["homeTeam"]["score"] if m["homeTeam"]["score"] else "0"
                    away_score = m["awayTeam"]["score"] if m["awayTeam"]["score"] else "0"

                    kickoff_utc = datetime.strptime(m["kickoff"], "%Y-%m-%dT%H:%M:%SZ")
                    kickoff_gmt3 = kickoff_utc + timedelta(hours=3)
                    kickoff_str = kickoff_gmt3.strftime("%Y-%m-%d %H:%M")

                    matches.append({
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

# ---------- WHERESTHEMATCH ----------
def fetch_wheresthematch_matches():
    url = "https://www.wheresthematch.com/football-today/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    matches = []

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"⚠️ Error fetching WherestheMatch: {e}")
        return matches

    soup = BeautifulSoup(response.text, 'html.parser')
    for row in soup.find_all('tr'):
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
            bst = pytz.timezone('Europe/London')
            eat = pytz.timezone('Africa/Nairobi')
            bst_time = bst.localize(datetime.strptime(f"{datetime.today().date()} {time_span.get_text(strip=True)}", "%Y-%m-%d %H:%M"))
            kickoff_str = bst_time.astimezone(eat).strftime("%Y-%m-%d %H:%M")

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
    return matches

# ---------- DADDYLIVE ----------
def fetch_daddylive_matches():
    url = "https://daddylivestream.com/schedule/schedule-generated.php"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://daddylivestream.com/",
        "Origin": "https://daddylivestream.com"
    }
    matches = []
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        schedule = response.json()
        for _, categories in schedule.items():
            if "Soccer" not in categories:
                continue
            for event in categories["Soccer"]:
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
    except Exception as e:
        print(f"⚠️ Error fetching DaddyLive: {e}")
    return matches

# ---------- ALLFOOTBALL ----------
def fetch_allfootball_matches():
    url = "https://m.allfootballapp.com/matchs"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": "https://www.allfootballapp.com/"
    }
    matches = []
    scraper = cloudscraper.create_scraper()
    try:
        resp = scraper.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        text = resp.text

        idx = text.find('"matchListStore":')
        if idx == -1:
            print("⚠️ Could not find JSON snippet on AllFootball page.")
            return matches

        snippet = text[idx:]
        end_idx = snippet.find('}</script>')
        if end_idx != -1:
            snippet = snippet[:end_idx+1]
        snippet = "{" + snippet
        data = json.loads(snippet)
        raw_matches = data.get("matchListStore", {}).get("currentListData", [])

        local_tz = pytz.timezone("Africa/Nairobi")
        today_local = datetime.now(local_tz).date()

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
                    "away_logo": m.get("team_B_logo", "No logo"),
                    "home_score": str(m.get("fs_A", "0")),
                    "away_score": str(m.get("fs_B", "0"))
                })
            except Exception as e:
                print(f"⚠️ Error processing AllFootball match: {e}")
                continue
    except Exception as e:
        print(f"⚠️ Error fetching AllFootball: {e}")
    return matches

# ---------- MERGE ----------
def merge_matches():
    onefootball = fetch_onefootball_matches()
    wtm = fetch_wheresthematch_matches()
    daddylive = fetch_daddylive_matches()
    allfootball = fetch_allfootball_matches()
    merged = []

    for om in onefootball:
        matched = False
        for wm in wtm:
            if teams_match(om["home"], om["away"], wm["home"], wm["away"]):
                matched = True
                channels = wm["channels"].copy()
                for dm in daddylive:
                    if teams_match(om["home"], om["away"], dm["home"], dm["away"]):
                        for ch in dm["channels"]:
                            if ch not in channels:
                                channels.append(ch)
                merged.append({**om, "channels": channels})
                break

        if not matched:
            for am in allfootball:
                if teams_match(om["home"], om["away"], am["home"], am["away"]):
                    channels = []
                    for dm in daddylive:
                        if teams_match(om["home"], om["away"], dm["home"], dm["away"]):
                            for ch in dm["channels"]:
                                if ch not in channels:
                                    channels.append(ch)
                    merged.append({**om, "channels": channels})
                    matched = True
                    break

    def kickoff_key(match):
        try:
            return datetime.strptime(match["kickoff"], "%Y-%m-%d %H:%M")
        except Exception:
            return datetime.max
    merged.sort(key=kickoff_key)

    for m in merged:
        print(f"🏟️ Match: {m['home']} Vs {m['away']}")
        print(f"🕒 Start: {m['kickoff']} (GMT+3)")
        print(f"📍 Tournament: {m['competition']}")
        print(f"📺 Channels: {', '.join(m['channels']) if m['channels'] else 'Not specified'}")
        print(f"🖼️ Home Logo: {m['home_logo']}")
        print(f"🖼️ Away Logo: {m['away_logo']}")
        print(f"⚽ Score: {m['home_score']} | {m['away_score']}")
        print("-" * 50)

if __name__ == "__main__":
    merge_matches()
