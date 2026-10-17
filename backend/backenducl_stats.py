# backend/ucl_stats.py
"""
Получает статистику матча (углы, карточки) из Free API Live Football Data (RapidAPI).
Только для Лиги чемпионов (UCL).
"""
import requests
import asyncio
from datetime import datetime

# ⚠️ ВСТАВЬ СВОЙ КЛЮЧ ОТ RAPIDAPI
RAPIDAPI_KEY = "42f24098f4msh476408b77cb8024p14bf3djsn8ca4a7d38b75"

BASE_URL = "https://free-api-live-football-data.p.rapidapi.com"
HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "free-api-live-football-data.p.rapidapi.com"
}


def _find_event_id_sync(home_team: str, away_team: str, match_date: str) -> str:
    """
    Ищет eventId в API по дате и названиям команд.
    Дата в формате YYYYMMDD.
    """
    try:
        date_str = match_date[:10].replace("-", "")

        url = f"{BASE_URL}/football-get-matches-by-date"
        params = {"date": date_str}

        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"[UCL Stats] HTTP {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        events = data.get("response", {}).get("events", []) or []

        home_lower = home_team.lower()
        away_lower = away_team.lower()

        for ev in events:
            h_name = (ev.get("home", {}).get("name") or "").lower()
            a_name = (ev.get("away", {}).get("name") or "").lower()

            # Убираем общие суффиксы
            skip = ["fc", "cf", "ac", "sc", "afc", "as", "ss", "ssc"]
            h_clean = " ".join(w for w in h_name.split() if w not in skip)
            a_clean = " ".join(w for w in a_name.split() if w not in skip)
            home_clean = " ".join(w for w in home_lower.split() if w not in skip)
            away_clean = " ".join(w for w in away_lower.split() if w not in skip)

            if (home_clean in h_clean or h_clean in home_clean) and \
               (away_clean in a_clean or a_clean in away_clean):
                return str(ev.get("id"))

        print(f"[UCL Stats] Матч не найден: {home_team} — {away_team} на {date_str}")
        return None
    except Exception as e:
        print(f"[UCL Stats] Ошибка поиска: {e}")
        return None


def _fetch_stats_sync(event_id: str) -> dict:
    """Синхронный запрос статистики по event_id."""
    try:
        url = f"{BASE_URL}/football-get-stats-event-by-event-id"
        params = {"eventId": event_id}

        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"[UCL Stats] HTTP {resp.status_code}")
            return {}

        data = resp.json()
        stats_groups = data.get("response", {}).get("stats", []) or []

        home_corners = 0
        away_corners = 0
        home_cards = 0
        away_cards = 0

        for group in stats_groups:
            for s in group.get("stats", []):
                key = (s.get("key") or "").lower()

                if key == "corners":
                    vals = s.get("stats") or [0, 0]
                    home_corners = vals[0] or 0
                    away_corners = vals[1] or 0

                elif key == "yellow_cards":
                    vals = s.get("stats") or [0, 0]
                    home_cards += vals[0] or 0
                    away_cards += vals[1] or 0

                elif key == "red_cards":
                    vals = s.get("stats") or [0, 0]
                    home_cards += vals[0] or 0
                    away_cards += vals[1] or 0

        return {
            "home_corners": home_corners,
            "away_corners": away_corners,
            "total_corners": home_corners + away_corners,
            "home_cards": home_cards,
            "away_cards": away_cards,
            "total_cards": home_cards + away_cards,
        }
    except Exception as e:
        print(f"[UCL Stats] Ошибка: {e}")
        return {}


async def get_ucl_match_stats(home_team: str, away_team: str, match_date: str) -> dict:
    """Асинхронная обёртка: ищет eventId по названиям и получает статистику."""
    def _combined():
        event_id = _find_event_id_sync(home_team, away_team, match_date)
        if not event_id:
            return {}
        return _fetch_stats_sync(event_id)

    return await asyncio.to_thread(_combined)