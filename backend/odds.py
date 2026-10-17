# backend/odds.py
"""
Кэфы из The Odds API (П1/Х/П2 + Тотал 2.5).
Остальные рынки — через API-Football (см. api_football.py).
"""
import httpx
from datetime import datetime, timedelta

ODDS_API_KEY = "795ad4b7448c79b120c7670640fce1f7"
BASE_URL = "https://api.the-odds-api.com/v4/sports"

LEAGUE_MAP = {
    "EPL":        "soccer_epl",
    "LaLiga":     "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "SerieA":     "soccer_italy_serie_a",
    "Ligue1":     "soccer_france_ligue_one",
    "UCL":        "soccer_uefa_champs_league",
}

_cache = {}
_cache_time = {}
CACHE_TTL = timedelta(hours=12)


def _is_cache_valid(key: str) -> bool:
    if key not in _cache_time:
        return False
    return datetime.utcnow() - _cache_time[key] < CACHE_TTL


async def fetch_league_odds(league_key: str) -> dict:
    if league_key not in LEAGUE_MAP:
        return {}

    cache_key = league_key
    if _is_cache_valid(cache_key):
        return _cache[cache_key]

    sport = LEAGUE_MAP[league_key]

    url = (
        f"{BASE_URL}/{sport}/odds/"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions=eu"
        f"&markets=h2h,totals"
        f"&oddsFormat=decimal"
    )

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=20)

            if resp.status_code != 200:
                print(f"[Odds] {league_key}: HTTP {resp.status_code} — {resp.text[:200]}")
                return {}

            data = resp.json()
            result = {}

            for event in data:
                home = event.get("home_team", "").lower().strip()
                if not home:
                    continue

                best = {"home": 0, "draw": 0, "away": 0, "over25": 0, "under25": 0}

                for book in event.get("bookmakers", []):
                    for market in book.get("markets", []):
                        key = market.get("key")

                        if key == "h2h":
                            for o in market.get("outcomes", []):
                                name = o.get("name", "").lower()
                                price = o.get("price", 0)
                                if name == home:
                                    best["home"] = max(best["home"], price)
                                elif name == "draw":
                                    best["draw"] = max(best["draw"], price)
                                else:
                                    best["away"] = max(best["away"], price)

                        elif key == "totals":
                            for o in market.get("outcomes", []):
                                if o.get("point") == 2.5:
                                    price = o.get("price", 0)
                                    if o.get("name") == "Over":
                                        best["over25"] = max(best["over25"], price)
                                    else:
                                        best["under25"] = max(best["under25"], price)

                result[home] = best

            _cache[cache_key] = result
            _cache_time[cache_key] = datetime.utcnow()
            print(f"[Odds] {league_key}: загружено {len(result)} матчей")
            return result

        except Exception as e:
            print(f"[Odds] Ошибка для {league_key}: {e}")
            return {}


async def get_match_odds(league_key: str, home_team: str) -> dict:
    all_odds = await fetch_league_odds(league_key)
    if not all_odds:
        return {}

    home_lower = home_team.lower().strip()

    if home_lower in all_odds:
        return all_odds[home_lower]

    skip_words = {"fc", "cfc", "ac", "sc", "afc", "cf", "as", "ss", "ssc", "cd", "ud"}
    parts = [w for w in home_lower.split() if w not in skip_words]

    for api_home, odds in all_odds.items():
        api_parts = [w for w in api_home.split() if w not in skip_words]

        if parts and api_parts and parts[0] == api_parts[0]:
            return odds

        if parts and (parts[0] in api_home or api_home in home_lower):
            return odds

    return {}