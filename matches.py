import requests
import re
import json
import os
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import pytz
from contextlib import redirect_stdout

# ---------- HELPER ----------
def normalize_team_name(name):
    return re.sub(r'[^a-z0-9]', '', str(name).lower())

# ---------- ONEFOOTBALL ----------
def fetch_onefootball_matches():
    url = "https://onefootball.com/en/matches"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Android; Mobile; rv:109.0) Gecko/109.0 Firefox/109.0'
    }
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
                match_list = comp["contentType"]["matchCardsList"]["matchCards"]

                for m in match_list:
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
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    matches = []

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"⚠️ Error fetching WherestheMatch: {e}")
        return matches

    soup = BeautifulSoup(response.text, 'html.parser')
    match_rows = soup.find_all('tr')

    for row in match_rows:
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
        time_str = time_span.get_text(strip=True) if time_span else None
        kickoff_str = "Unknown"
        if time_str:
            bst = pytz.timezone('Europe/London')
            eat = pytz.timezone('Africa/Nairobi')
            bst_time = bst.localize(datetime.strptime(f"{datetime.today().date()} {time_str}", "%Y-%m-%d %H:%M"))
            kickoff_str = bst_time.astimezone(eat).strftime("%Y-%m-%d %H:%M")

        channels = []
        if channels_cell:
            channel_imgs = channels_cell.find_all('img', class_='channel')
            channels = [img.get('title', 'Unknown Channel') for img in channel_imgs]
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
                channels = ch1 + ch2 if (ch1 or ch2) else []

                matches.append({
                    "home": home,
                    "away": away,
                    "competition": comp,
                    "channels": channels
                })
    except Exception as e:
        print(f"⚠️ Error fetching DaddyLive: {e}")

    return matches

# ---------- MERGE ----------
def merge_matches():
    onefootball_matches = fetch_onefootball_matches()
    wtm_matches = fetch_wheresthematch_matches()
    daddylive_matches = fetch_daddylive_matches()

    merged = []

    for om in onefootball_matches:
        for wm in wtm_matches:
            if (normalize_team_name(om["home"]) == normalize_team_name(wm["home"]) and
                normalize_team_name(om["away"]) == normalize_team_name(wm["away"])):

                channels = wm["channels"].copy()

                for dm in daddylive_matches:
                    if (normalize_team_name(om["home"]) == normalize_team_name(dm["home"]) and
                        normalize_team_name(om["away"]) == normalize_team_name(dm["away"])):
                        for ch in dm["channels"]:
                            if ch not in channels:
                                channels.append(ch)

                merged.append({
                    "home": om["home"],
                    "away": om["away"],
                    "competition": om["competition"],
                    "kickoff": om["kickoff"],
                    "home_logo": om["home_logo"],
                    "away_logo": om["away_logo"],
                    "home_score": om["home_score"],
                    "away_score": om["away_score"],
                    "channels": channels
                })

    # Sort by kickoff
    def kickoff_key(match):
        try:
            return datetime.strptime(match["kickoff"], "%Y-%m-%d %H:%M")
        except:
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

# ---------- MAIN ----------
if __name__ == "__main__":
    with open("matches.txt", "w", encoding="utf-8") as f:
        with redirect_stdout(f):
            merge_matches()
