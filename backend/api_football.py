# backend/api_football.py
"""
API-Football (api-sports.io) — реальные кэфы и статистика.
Используется для:
  - Кэфы на тоталы 1.5 / 3.5 / 4.5 и другие линии
  - Кэфы на углы и карточки
  - Статистика матчей (углы, карточки) — для ЛЧ и других лиг
"""
import requests
import asyncio
from datetime import datetime, timedelta

# ⚠️ ВСТАВЬ СВОЙ НОВЫЙ КЛЮЧ
API_FOOTBALL_KEY = "d9e0c679d4cd4e1a72844df2e3e822e8"

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {
    "x-apisports-key": API_FOOTBALL_KEY,
}

# ID лиг в API-Football (для поиска матча)
LEAGUE_IDS = {
    "EPL": 39,        # Premier League
    "LaLiga": 140,    # La Liga
    "Bundesliga": 78, # Bundesliga
    "SerieA": 135,    # Serie A
    "Ligue1": 61,     # Ligue 1
    "UCL": 2,         # UEFA Champions League
}

_cache = {}
_cache_time = {}
CACHE_TTL = timedelta(hours=6)


def _is_cache_valid(key):
    if key not in _cache_time:
        return False
    return datetime.utcnow() - _cache_time[key] < CACHE_TTL


def _find_fixture_sync(league_key: str, home_team: str, away_team: str, match_date: str):
    """Находит fixture_id в API-Football по дате и названиям команд."""
    league_id = LEAGUE_IDS.get(league_key)
    if not league_id:
        return None

    try:
        date_str = match_date[:10]  # YYYY-MM-DD

        url = f"{BASE_URL}/fixtures"
        params = {
            "league": league_id,
            "season": 2026,
            "from": date_str,
            "to": date_str,
        }
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)

        if resp.status_code != 200:
            print(f"[API-Football] HTTP {resp.status_code} — {resp.text[:200]}")
            return None

        data = resp.json()
        fixtures = data.get("response", []) or []

        home_lower = home_team.lower()
        away_lower = away_team.lower()
        skip = {"fc", "cfc", "ac", "sc", "afc", "cf", "as", "ss", "ssc", "cd", "ud"}

        def clean(name):
            return " ".join(w for w in name.split() if w not in skip)

        home_clean = clean(home_lower)
        away_clean = clean(away_lower)

        for f in fixtures:
            teams = f.get("teams", {})
            h_name = (teams.get("home", {}).get("name") or "").lower()
            a_name = (teams.get("away", {}).get("name") or "").lower()
            h_clean = clean(h_name)
            a_clean = clean(a_name)

            if (home_clean in h_clean or h_clean in home_clean) and \
               (away_clean in a_clean or a_clean in away_clean):
                return f.get("fixture", {}).get("id")

        print(f"[API-Football] Матч не найден: {home_team} — {away_team} ({date_str})")
        return None

    except Exception as e:
        print(f"[API-Football] Ошибка поиска: {e}")
        return None


def _fetch_odds_sync(fixture_id: int):
    """
    Получает все кэфы для матча из API-Football.
    Возвращает: dict с рынками.
    """
    try:
        url = f"{BASE_URL}/odds"
        params = {"fixture": fixture_id}
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)

        if resp.status_code != 200:
            print(f"[API-Football] Odds HTTP {resp.status_code}")
            return {}

        data = resp.json()
        response = data.get("response", []) or []
        if not response:
            return {}

        # Берём первого букмекера из списка
        bookmakers = response[0].get("bookmakers", []) or []
        if not bookmakers:
            return {}

        bets = bookmakers[0].get("bets", []) or []

        result = {}

        for bet in bets:
            bet_id = bet.get("id")
            bet_name = (bet.get("name") or "").lower()
            values = bet.get("values", []) or []

            # ===== ИСХОД (Match Winner) =====
            if bet_id == 1:
                for v in values:
                    val = (v.get("value") or "").lower()
                    odd = v.get("odd")
                    try:
                        odd = float(odd)
                    except (ValueError, TypeError):
                        continue
                    if val == "home":
                        result["home"] = odd
                    elif val == "draw":
                        result["draw"] = odd
                    elif val == "away":
                        result["away"] = odd

            # ===== ТОТАЛЫ (Goals Over/Under) =====
            elif bet_id == 5:
                for v in values:
                    val = (v.get("value") or "").lower()
                    odd = v.get("odd")
                    try:
                        odd = float(odd)
                    except (ValueError, TypeError):
                        continue

                    # over_2.5 / under_2.5 / over_1.5 / etc.
                    if "over 1.5" in val:
                        result["over15"] = odd
                    elif "under 1.5" in val:
                        result["under15"] = odd
                    elif "over 2.5" in val:
                        result["over25"] = odd
                    elif "under 2.5" in val:
                        result["under25"] = odd
                    elif "over 3.5" in val:
                        result["over35"] = odd
                    elif "under 3.5" in val:
                        result["under35"] = odd
                    elif "over 4.5" in val:
                        result["over45"] = odd
                    elif "under 4.5" in val:
                        result["under45"] = odd

            # ===== ОБЕ ЗАБЬЮТ =====
            elif bet_id == 8:
                for v in values:
                    val = (v.get("value") or "").lower()
                    odd = v.get("odd")
                    try:
                        odd = float(odd)
                    except (ValueError, TypeError):
                        continue
                    if val == "yes":
                        result["btts_yes"] = odd
                    elif val == "no":
                        result["btts_no"] = odd

            # ===== УГЛОВЫЕ (Corners Over/Under) =====
            elif bet_id == 45:
                for v in values:
                    val = (v.get("value") or "").lower()
                    odd = v.get("odd")
                    try:
                        odd = float(odd)
                    except (ValueError, TypeError):
                        continue
                    if "over 9.5" in val or "over 10.5" in val:
                        result["corners_over"] = odd
                    elif "under 9.5" in val or "under 10.5" in val:
                        result["corners_under"] = odd

            # ===== КАРТОЧКИ (Cards Over/Under) =====
            elif bet_id == 76:
                for v in values:
                    val = (v.get("value") or "").lower()
                    odd = v.get("odd")
                    try:
                        odd = float(odd)
                    except (ValueError, TypeError):
                        continue
                    if "over 3.5" in val or "over 4.5" in val:
                        result["cards_over"] = odd
                    elif "under 3.5" in val or "under 4.5" in val:
                        result["cards_under"] = odd

        return result

    except Exception as e:
        print(f"[API-Football] Odds ошибка: {e}")
        return {}


def _fetch_stats_sync(fixture_id: int):
    """Статистика матча — углы и карточки."""
    try:
        url = f"{BASE_URL}/fixtures/statistics"
        params = {"fixture": fixture_id}
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)

        if resp.status_code != 200:
            print(f"[API-Football] Stats HTTP {resp.status_code}")
            return {}

        data = resp.json()
        stats_list = data.get("response", []) or []
        if len(stats_list) < 2:
            return {}

        home_corners = 0
        away_corners = 0
        home_cards = 0
        away_cards = 0

        for idx, team_stats in enumerate(stats_list):
            is_home = (idx == 0)
            for s in team_stats.get("statistics", []):
                stype = (s.get("type") or "").lower()
                value = s.get("value")
                try:
                    value = int(value) if value is not None else 0
                except (ValueError, TypeError):
                    value = 0

                if "corner" in stype:
                    if is_home:
                        home_corners = value
                    else:
                        away_corners = value

                if "yellow" in stype or "red" in stype:
                    if is_home:
                        home_cards += value
                    else:
                        away_cards += value

        return {
            "home_corners": home_corners,
            "away_corners": away_corners,
            "total_corners": home_corners + away_corners,
            "home_cards": home_cards,
            "away_cards": away_cards,
            "total_cards": home_cards + away_cards,
        }
    except Exception as e:
        print(f"[API-Football] Stats ошибка: {e}")
        return {}


async def get_api_football_odds(league_key: str, home_team: str, away_team: str, match_date: str) -> dict:
    """Асинхронная обёртка: кэфы из API-Football."""
    cache_key = f"odds_{home_team}_{away_team}_{match_date[:10]}"
    if _is_cache_valid(cache_key):
        return _cache[cache_key]

    def _combined():
        fixture_id = _find_fixture_sync(league_key, home_team, away_team, match_date)
        if not fixture_id:
            return {}
        return _fetch_odds_sync(fixture_id)

    result = await asyncio.to_thread(_combined)
    _cache[cache_key] = result
    _cache_time[cache_key] = datetime.utcnow()
    return result


async def get_api_football_stats(league_key: str, home_team: str, away_team: str, match_date: str) -> dict:
    """Асинхронная обёртка: статистика из API-Football."""
    cache_key = f"stats_{home_team}_{away_team}_{match_date[:10]}"
    if _is_cache_valid(cache_key):
        return _cache[cache_key]

    def _combined():
        fixture_id = _find_fixture_sync(league_key, home_team, away_team, match_date)
        if not fixture_id:
            return {}
        return _fetch_stats_sync(fixture_id)

    result = await asyncio.to_thread(_combined)
    _cache[cache_key] = result
    _cache_time[cache_key] = datetime.utcnow()
    return result