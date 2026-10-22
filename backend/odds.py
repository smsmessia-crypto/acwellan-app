# backend/odds.py
import httpx
from datetime import datetime, timedelta

ODDS_API_KEY = "795ad4b7448c79b120c7670640fce1f7" # Твой ключ
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

# Слова, которые нужно игнорировать при сравнении названий команд
# Это решает проблему "FC Internazionale" vs "Inter Milan" и "Aston Villa FC" vs "Aston Villa"
SKIP_WORDS = {
    "fc", "cfc", "ac", "sc", "afc", "cf", "as", "ss", "ssc", "cd", "ud",
    "united", "city", "town", "athletic", "sporting", "real", "atletico",
    "inter", "internazionale", "milano", "milan", # Для Интера
    "aston", "villa", # Для Астон Виллы
}


def _is_cache_valid(key: str) -> bool:
    if key not in _cache_time:
        return False
    return datetime.utcnow() - _cache_time[key] < CACHE_TTL


def _normalize(name: str) -> str:
    """Убирает лишние слова и приводит к нижнему регистру."""
    if not name:
        return ""
    parts = []
    for w in name.lower().strip().split():
        w = w.replace(".", "").replace(",", "").strip()
        if not w:
            continue
        if w in SKIP_WORDS:
            continue
        if w.isdigit():
            continue
        parts.append(w)
    return " ".join(parts) if parts else name.lower().strip()


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

    target_home = _normalize(home_team)

    # 1. Прямое совпадение (после нормализации)
    for api_home, odds in all_odds.items():
        if _normalize(api_home) == target_home:
            return odds

    # 2. Частичное совпадение (первое слово)
    target_parts = target_home.split()
    if not target_parts:
        return {}

    target_first = target_parts[0]

    for api_home, odds in all_odds.items():
        api_parts = _normalize(api_home).split()
        if not api_parts:
            continue
        api_first = api_parts[0]

        # Сравниваем первые значимые слова
        if target_first == api_first:
            return odds

        # Или если одно слово содержится в другом (для "Астон Вилла" и "Aston Villa")
        if target_first in api_home or api_first in home_team.lower():
            return odds

    print(f"[Odds] Не удалось сопоставить '{home_team}' с командами из API.")
    return {}