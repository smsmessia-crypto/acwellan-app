# backend/sportsdb.py
"""
Получает матчи из Football-Data.org.
Окно: -7 дней (прошедшие) ... +60 дней (будущие).
Лига Европы (UEL) убрана — не входит в бесплатный тариф.
"""
import httpx
from datetime import datetime, timedelta

API_KEY = "521746c93205411ab096def62b1f9ac8"
BASE_URL = "https://api.football-data.org/v4"

HEADERS = {"X-Auth-Token": API_KEY}

LEAGUES = {
    "EPL":        {"id": "PL",  "name": "Premier League"},
    "LaLiga":     {"id": "PD",  "name": "La Liga"},
    "Bundesliga": {"id": "BL1", "name": "Bundesliga"},
    "SerieA":     {"id": "SA",  "name": "Serie A"},
    "Ligue1":     {"id": "FL1", "name": "Ligue 1"},
    "UCL":        {"id": "CL",  "name": "UEFA Champions League"},
}


async def fetch_matches(league_key: str, days_ahead: int = 60) -> list:
    league = LEAGUES.get(league_key)
    if not league:
        return []

    today = datetime.utcnow().date()
    date_from = (today - timedelta(days=7)).isoformat()
    date_to = (today + timedelta(days=days_ahead)).isoformat()

    url = (
        f"{BASE_URL}/competitions/{league['id']}/matches"
        f"?dateFrom={date_from}&dateTo={date_to}"
    )

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=HEADERS, timeout=20)

            if resp.status_code != 200:
                print(f"[Football-Data] {league_key}: HTTP {resp.status_code} — {resp.text[:200]}")
                return []

            data = resp.json()
            matches = data.get("matches") or []
            result = []
            for m in matches:
                score = m.get("score", {}).get("fullTime", {})
                status = m.get("status", "")
                is_finished = status in ("FINISHED", "AWARDED")

                result.append({
                    "event_id": str(m.get("id")),
                    "league": league_key,
                    "league_name": league["name"],
                    "home_team": m.get("homeTeam", {}).get("name") or "TBD",
                    "away_team": m.get("awayTeam", {}).get("name") or "TBD",
                    "match_date": parse_date(m.get("utcDate")),
                    "home_score": score.get("home") if is_finished else None,
                    "away_score": score.get("away") if is_finished else None,
                    "status": "finished" if is_finished else "upcoming",
                })

            print(f"[Football-Data] {league_key}: {len(result)} матчей")
            return result

        except Exception as e:
            print(f"[Football-Data] Ошибка для {league_key}: {e}")
            return []


def parse_date(value: str):
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow()