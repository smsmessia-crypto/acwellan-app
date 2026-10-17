# backend/match_stats.py
"""
Получает статистику матча (углы, карточки) из 5DollarFootballAPI.
"""
from fivedollarfootball import Client

API_KEY = "fb_live_g0YlVRgUfsqetrl1b2gBH4JG5Oo7esSc"

_client = Client(API_KEY)


async def get_match_stats(fixture_id: str) -> dict:
    """
    Возвращает статистику матча: углы, карточки.
    """
    try:
        fixture = _client.fixture(int(fixture_id), include=["events", "stats"])
    except Exception as e:
        print(f"[Stats] Ошибка для fixture {fixture_id}: {e}")
        return {}

    # Извлекаем углы и карточки из ответа
    home_corners = 0
    away_corners = 0
    home_cards = 0
    away_cards = 0

    # Ищем в статистике
    stats = fixture.get("statistics", [])
    for s in stats:
        stype = s.get("type", "").lower()
        if "corner" in stype:
            home_corners = s.get("home", 0) or 0
            away_corners = s.get("away", 0) or 0

    # Ищем в событиях (карточки)
    events = fixture.get("events", [])
    for e in events:
        etype = e.get("type", "").lower()
        if "card" in etype or "yellow" in etype or "red" in etype:
            if e.get("side") == "home":
                home_cards += 1
            elif e.get("side") == "away":
                away_cards += 1

    return {
        "home_corners": home_corners,
        "away_corners": away_corners,
        "total_corners": home_corners + away_corners,
        "home_cards": home_cards,
        "away_cards": away_cards,
        "total_cards": home_cards + away_cards,
    }