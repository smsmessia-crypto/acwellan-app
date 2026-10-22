# backend/odds_api.py
import os
import httpx
from datetime import datetime
from collections import defaultdict, deque

# ⚠️ ВСТАВЬ СВОЙ КЛЮЧ (получи на the-odds-api.com)
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "ТВОЙ_КЛЮЧ_ЗДЕСЬ")

# Маппинг твоих лиг на sport_key в The Odds API
LEAGUE_TO_SPORT = {
    "EPL": "soccer_epl",
    "LaLiga": "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "SerieA": "soccer_italy_serie_a",
    "Ligue1": "soccer_france_ligue_one",
    "UCL": "soccer_uefa_champs_league",
}

# Кэш, чтобы не тратить лимит на повторные запросы
_cache = {}
_cache_time = {}
CACHE_TTL_SECONDS = 3600  # 1 час

def _is_cache_valid(key):
    if key not in _cache_time:
        return False
    return (datetime.utcnow() - _cache_time[key]).total_seconds() < CACHE_TTL_SECONDS

def _normalize(name: str) -> str:
    """Убираем лишние слова для сравнения названий команд."""
    if not name:
        return ""
    skip = {"fc", "cfc", "ac", "sc", "afc", "cf", "as", "ss", "ssc", "cd", "ud", "vfb", "sv", "vfl"}
    parts = [w for w in name.lower().strip().split() if w not in skip and not w.isdigit()]
    return " ".join(parts) if parts else name.lower().strip()

async def get_real_odds(league: str, home_team: str, away_team: str) -> dict:
    """
    Возвращает реальные кэфы с The Odds API:
    {"home": 2.10, "draw": 3.40, "away": 3.20, "over25": 1.85, "under25": 1.95}
    Если не нашли — пустой словарь.
    """
    sport_key = LEAGUE_TO_SPORT.get(league)
    if not sport_key:
        print(f"[TheOddsAPI] Нет sport_key для лиги '{league}'")
        return {}

    cache_key = f"{sport_key}_{home_team}_{away_team}"
    if _is_cache_valid(cache_key):
        return _cache[cache_key]

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": THE_ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                print(f"[TheOddsAPI] HTTP {resp.status_code}: {resp.text[:200]}")
                return {}
            events = resp.json()
    except Exception as e:
        print(f"[TheOddsAPI] Ошибка запроса: {e}")
        return {}

    home_norm = _normalize(home_team)
    away_norm = _normalize(away_team)

    for event in events:
        ev_home = _normalize(event.get("home_team", ""))
        ev_away = _normalize(event.get("away_team", ""))

        # Ищем матч по названиям команд
        if not ((home_norm in ev_home or ev_home in home_norm) and
                (away_norm in ev_away or ev_away in away_norm)):
            continue

        result = {}
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                if market["key"] == "h2h" and not all(k in result for k in ("home", "draw", "away")):
                    for o in market["outcomes"]:
                        name = _normalize(o["name"])
                        price = o["price"]
                        if name == home_norm:
                            result.setdefault("home", price)
                        elif name in ("draw", "ничья"):
                            result.setdefault("draw", price)
                        else:
                            result.setdefault("away", price)

                elif market["key"] == "totals":
                    for o in market["outcomes"]:
                        if abs(o.get("point", 0) - 2.5) > 1e-6:
                            continue
                        if o["name"] == "Over":
                            result.setdefault("over25", o["price"])
                        elif o["name"] == "Under":
                            result.setdefault("under25", o["price"])

            if all(k in result for k in ("home", "draw", "away", "over25", "under25")):
                _cache[cache_key] = result
                _cache_time[cache_key] = datetime.utcnow()
                return result

        if result:
            _cache[cache_key] = result
            _cache_time[cache_key] = datetime.utcnow()
            return result

    print(f"[TheOddsAPI] Матч не найден: {home_team} — {away_team}")
    return {}