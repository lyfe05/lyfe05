import re
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------- HELPERS ----------
def normalize_team_name(name):
    """Normalize team names for comparison"""
    return re.sub(r'[^a-z0-9]', '', name.lower())

def fetch_match_score_from_onefootball(home_team, away_team):
    """Fetch score for a specific match from OneFootball"""
    url = "https://onefootball.com/en/matches"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        json_pattern = r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>'
        match = re.search(json_pattern, response.text, re.DOTALL)

        if not match:
            print(f"❌ No JSON data found for {home_team} vs {away_team}")
            return None, None

        json_data = json.loads(match.group(1))
        
        # Normalize the team names we're looking for
        norm_home = normalize_team_name(home_team)
        norm_away = normalize_team_name(away_team)
        
        # Recursively search for matches in the JSON data
        def find_matches(data):
            matches = []
            if isinstance(data, dict):
                # Check if this is a match object
                if "homeTeam" in data and "awayTeam" in data:
                    matches.append(data)
                # Recursively search nested structures
                for value in data.values():
                    matches.extend(find_matches(value))
            elif isinstance(data, list):
                for item in data:
                    matches.extend(find_matches(item))
            return matches

        all_matches = find_matches(json_data)
        
        # Look for our specific match
        for match_data in all_matches:
            try:
                match_home = match_data["homeTeam"]["name"]
                match_away = match_data["awayTeam"]["name"]
                
                # Check if this is the match we're looking for
                if (normalize_team_name(match_home) == norm_home and 
                    normalize_team_name(match_away) == norm_away):
                    
                    home_score = str(match_data["homeTeam"].get("score", "0") or "0")
                    away_score = str(match_data["awayTeam"].get("score", "0") or "0")
                    
                    print(f"✅ Found score: {home_team} {home_score}-{away_score} {away_team}")
                    return home_score, away_score
                    
            except Exception as e:
                continue
        
        print(f"❌ Match not found: {home_team} vs {away_team}")
        return None, None
                
    except Exception as e:
        print(f"⚠️ Error fetching data for {home_team} vs {away_team}: {e}")
        return None, None

def update_scores():
    """Update scores in matches.txt by reading each match and fetching its score"""
    try:
        with open("matches.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
        print(f"📖 Read {len(lines)} lines from matches.txt")
    except FileNotFoundError:
        print("⚠️ matches.txt not found.")
        return

    updated_lines = []
    changes_made = False
    current_match = None
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if line.startswith("🏟️ Match: "):
            # Extract teams from the match line
            try:
                parts = line.strip().split("Match: ")[1].split(" Vs ")
                home_team, away_team = parts[0].strip(), parts[1].strip()
                current_match = (home_team, away_team)
                print(f"\n🔍 Processing: {home_team} vs {away_team}")
            except Exception as e:
                print(f"⚠️ Error parsing match line: {e}")
                updated_lines.append(line)
                i += 1
                continue
            
            # Add the match line and all subsequent lines until we find the score line
            updated_lines.append(line)
            i += 1
            
            # Keep adding lines until we find the score line or separator
            while i < len(lines) and not lines[i].startswith("⚽ Score:") and not lines[i].startswith("--------------------------------------------------"):
                updated_lines.append(lines[i])
                i += 1
            
            # If we found a score line, process it
            if i < len(lines) and lines[i].startswith("⚽ Score:"):
                # Fetch the current score from OneFootball
                home_score, away_score = fetch_match_score_from_onefootball(home_team, away_team)
                
                if home_score is not None and away_score is not None:
                    new_score_line = f"⚽ Score: {home_score} | {away_score}\n"
                    current_score_line = lines[i]
                    
                    if current_score_line.strip() != new_score_line.strip():
                        print(f"🔄 Updating: {current_score_line.strip()} -> {new_score_line.strip()}")
                        updated_lines.append(new_score_line)
                        changes_made = True
                    else:
                        print(f"✅ Score unchanged: {new_score_line.strip()}")
                        updated_lines.append(current_score_line)
                else:
                    print("⏭️ Keeping original score (match not found)")
                    updated_lines.append(lines[i])
                
                i += 1
                
                # Skip the duplicate score line if it exists
                if i < len(lines) and lines[i].startswith("⚽ Score:"):
                    print("⏭️ Skipping duplicate score line")
                    i += 1
            else:
                print("⚠️ No score line found for this match")
                
        else:
            updated_lines.append(line)
            i += 1

    if changes_made:
        with open("matches.txt", "w", encoding="utf-8") as f:
            f.writelines(updated_lines)
        print(f"\n✅ Scores updated in matches.txt")
    else:
        print(f"\n✅ No score changes detected")

if __name__ == "__main__":
    update_scores()
