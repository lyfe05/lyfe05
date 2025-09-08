import re
import json
from datetime import datetime, timedelta
import requests

# ---------- HELPERS ----------
def normalize_team_name(name):
    """Normalize team names for comparison"""
    return re.sub(r'[^a-z0-9]', '', name.lower())

def fetch_onefootball_matches():
    """Fetch today's matches (with live scores) from OneFootball"""
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
                        "home_score": home_score,
                        "away_score": away_score
                    })
    except Exception as e:
        print(f"⚠️ Error fetching OneFootball: {e}")

    return matches

def should_update(matches):
    """Decide if updates should run based on match times"""
    if not matches:
        return False

    # Convert kickoff strings to datetime
    times = [datetime.strptime(m["kickoff"], "%Y-%m-%d %H:%M") for m in matches if m["kickoff"] != "Unknown"]
    if not times:
        return False

    first_match = min(times)
    last_match = max(times)

    start_time = first_match + timedelta(minutes=20)
    end_time = last_match + timedelta(hours=2)
    now = datetime.now()

    return start_time <= now <= end_time

def update_scores():
    """Update scores in matches.txt using latest OneFootball data"""
    try:
        with open("matches.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("⚠️ matches.txt not found. Run matches.py first.")
        return

    # Load fresh data
    live_matches = fetch_onefootball_matches()

    # Smart check: only update if we are in the match window
    if not should_update(live_matches):
        print("⏸️ Outside match window, skipping update.")
        return

    updated_lines = []
    for line in lines:
        if line.startswith("🏟️ Match: "):
            # Extract teams
            try:
                parts = line.strip().split("Match: ")[1].split(" Vs ")
                home_team, away_team = parts[0].strip(), parts[1].strip()
            except:
                updated_lines.append(line)
                continue

            # Find updated score
            for lm in live_matches:
                if (normalize_team_name(home_team) == normalize_team_name(lm["home"]) and
                    normalize_team_name(away_team) == normalize_team_name(lm["away"])):
                    updated_lines.append(line)  # keep the match line
                    updated_lines.append(f"⚽ Score: {lm['home_score']} | {lm['away_score']}\n")
                    break
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    with open("matches.txt", "w", encoding="utf-8") as f:
        f.writelines(updated_lines)

    print("✅ Scores updated in matches.txt")

if __name__ == "__main__":
    update_scores()
