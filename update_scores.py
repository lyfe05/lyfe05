import re
import json
from datetime import datetime, timedelta
import requests
from zoneinfo import ZoneInfo

# ---------- HELPERS ----------
def normalize_team_name(name):
    """Normalize team names for comparison"""
    return re.sub(r'[^a-z0-9]', '', name.lower())

def fetch_onefootball_matches():
    """Fetch today's matches (with live scores) from OneFootball"""
    url = "https://onefootball.com/en/matches"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    matches = []

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        json_pattern = r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>'
        match = re.search(json_pattern, response.text, re.DOTALL)

        if not match:
            print("❌ No JSON data found in response")
            return matches

        json_data = json.loads(match.group(1))
        
        # Try to find matches in the JSON structure
        matches_data = None
        
        # Look in props -> pageProps -> containers
        if "props" in json_data and "pageProps" in json_data["props"]:
            page_props = json_data["props"]["pageProps"]
            
            if "containers" in page_props:
                for container in page_props["containers"]:
                    if "type" in container and "fullWidth" in container["type"]:
                        comp = container["type"]["fullWidth"].get("component", {})
                        content_type = comp.get("contentType", {})
                        
                        if content_type.get("$case") == "matchCardsList":
                            matches_data = content_type["matchCardsList"].get("matchCards", [])
                            break
        
        if not matches_data:
            print("❌ Could not find match data in JSON structure")
            return matches

        for m in matches_data:
            try:
                # Extract competition name
                competition = "Unknown Tournament"
                if "tournament" in m:
                    competition = m["tournament"].get("name", "Unknown Tournament")
                elif "competition" in m:
                    competition = m["competition"].get("name", "Unknown Tournament")
                
                # Extract team names and scores
                home_team = m["homeTeam"]["name"]
                away_team = m["awayTeam"]["name"]
                
                # Handle scores - convert to string and handle None values
                home_score = str(m["homeTeam"].get("score", "0") or "0")
                away_score = str(m["awayTeam"].get("score", "0") or "0")
                
                # Handle kickoff time
                kickoff_str = "Unknown"
                if "kickoff" in m and m["kickoff"]:
                    try:
                        kickoff_utc = datetime.strptime(m["kickoff"], "%Y-%m-%dT%H:%M:%SZ")
                        kickoff_gmt3 = kickoff_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul"))
                        kickoff_str = kickoff_gmt3.strftime("%Y-%m-%d %H:%M")
                    except:
                        kickoff_str = m["kickoff"]

                matches.append({
                    "home": home_team,
                    "away": away_team,
                    "competition": competition,
                    "kickoff": kickoff_str,
                    "home_score": home_score,
                    "away_score": away_score
                })
                
            except Exception as e:
                print(f"⚠️ Error parsing match: {e}")
                continue
                
    except Exception as e:
        print(f"⚠️ Error fetching OneFootball: {e}")

    print(f"📊 Found {len(matches)} matches")
    for i, match in enumerate(matches[:5]):  # Show first 5 matches for debugging
        print(f"  {i+1}. {match['home']} {match['home_score']}-{match['away_score']} {match['away']}")
    
    return matches

def should_update(matches):
    """Always update if we have matches (remove time restrictions for now)"""
    if not matches:
        print("❌ No matches found, skipping update")
        return False
    
    print("✅ Matches found, proceeding with update")
    return True

def update_scores():
    """Update scores in matches.txt using latest OneFootball data"""
    try:
        with open("matches.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        print(f"📖 Read {len(lines)} lines from matches.txt")
    except FileNotFoundError:
        print("⚠️ matches.txt not found. Run matches.py first.")
        return

    # Load fresh data
    live_matches = fetch_onefootball_matches()

    # Smart check
    if not should_update(live_matches):
        print("⏸️ Outside match window, skipping update.")
        return

    updated_lines = []
    changes_made = False
    skip_next_score = False  # Flag to skip the second score line
    
    for i, line in enumerate(lines):
        if skip_next_score:
            skip_next_score = False
            continue
            
        if line.startswith("🏟️ Match: "):
            # Extract teams from the match line
            try:
                parts = line.strip().split("Match: ")[1].split(" Vs ")
                home_team, away_team = parts[0].strip(), parts[1].strip()
                print(f"🔍 Looking for: {home_team} vs {away_team}")
            except Exception as e:
                print(f"⚠️ Error parsing line {i}: {e}")
                updated_lines.append(line)
                continue

            # Find this match in live data
            found_match = None
            for lm in live_matches:
                if (normalize_team_name(home_team) == normalize_team_name(lm["home"]) and
                    normalize_team_name(away_team) == normalize_team_name(lm["away"])):
                    found_match = lm
                    break

            if found_match:
                # Add the match line
                updated_lines.append(line)
                
                # Check if next line is a score line
                if i + 1 < len(lines) and lines[i + 1].startswith("⚽ Score:"):
                    current_score = lines[i + 1].strip()
                    new_score = f"⚽ Score: {found_match['home_score']} | {found_match['away_score']}"
                    
                    if current_score != new_score:
                        print(f"🔄 Updating score: {current_score} -> {new_score}")
                        updated_lines.append(new_score + "\n")
                        changes_made = True
                    else:
                        updated_lines.append(lines[i + 1])
                
                # Skip the second score line (we'll handle it by not adding it)
                skip_next_score = True
                
            else:
                # Match not found in live data, keep original lines
                updated_lines.append(line)
                
        else:
            updated_lines.append(line)

    if changes_made:
        with open("matches.txt", "w", encoding="utf-8") as f:
            f.writelines(updated_lines)
        print("✅ Scores updated in matches.txt")
    else:
        print("✅ No score changes detected")

if __name__ == "__main__":
    update_scores()
