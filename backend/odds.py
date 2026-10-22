# backend/odds.py
import os
import numpy as np
import pandas as pd
import xgboost as xgb
from collections import defaultdict, deque

from api_football import get_api_football_odds

BASE_DIR = os.path.dirname(__file__)
MODELS_DIR = os.path.join(BASE_DIR, "models")

FEATURES = [
    "h_pts_last5", "h_goals_scored_last5", "h_goals_conceded_last5",
    "a_pts_last5", "a_goals_scored_last5", "a_goals_conceded_last5",
    "elo_h", "elo_a", "elo_diff",
    "psh", "psd", "psa", "avgh", "avgd", "avga",
]

ELO_START = 1500
ELO_K = 20

MIN_ODDS = 1.3
MAX_ODDS = 3.5

FALLBACK_PTS = 1.3
FALLBACK_SCORED = 1.3
FALLBACK_CONCEDED = 1.3
FALLBACK_ELO = 1500

_outcome = xgb.XGBClassifier(); _outcome.load_model(os.path.join(MODELS_DIR, "outcome_model.json"))
_over25 = xgb.XGBClassifier(); _over25.load_model(os.path.join(MODELS_DIR, "over25_model.json"))
_btts = xgb.XGBClassifier(); _btts.load_model(os.path.join(MODELS_DIR, "btts_model.json"))
_cards = xgb.XGBClassifier(); _cards.load_model(os.path.join(MODELS_DIR, "cards_model.json"))

_team_history = defaultdict(lambda: deque(maxlen=5))
_team_elo = defaultdict(lambda: ELO_START)

SKIP_WORDS = {
    "fc", "cfc", "ac", "sc", "afc", "cf", "as", "ss", "ssc", "cd", "ud",
    "vfb", "sv", "vfl", "tsg", "fsv", "bsc", "bvb", "rb",
    "1.", "2.", "3.", "1899", "1900", "1904", "1907", "1911", "1896",
    "07", "04", "05", "06", "08", "09", "98", "97",
    "united", "city", "town", "athletic", "sporting", "real", "atletico",
}


def _normalize_team(name: str) -> str:
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


def load_history_from_dataset(dataset_path):
    global _team_history, _team_elo
    df = pd.read_csv(dataset_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    for _, row in df.iterrows():
        home = _normalize_team(row["home_team"])
        away = _normalize_team(row["away_team"])

        elo_h = _team_elo[home]
        elo_a = _team_elo[away]
        expected_h = 1 / (1 + 10 ** ((elo_a - elo_h) / 400))

        if row["ftr"] == "H":
            score_h, score_a, h_pts, a_pts = 1.0, 0.0, 3, 0
        elif row["ftr"] == "A":
            score_h, score_a, h_pts, a_pts = 0.0, 1.0, 0, 3
        else:
            score_h, score_a, h_pts, a_pts = 0.5, 0.5, 1, 1

        _team_elo[home] = elo_h + ELO_K * (score_h - expected_h)
        _team_elo[away] = elo_a + ELO_K * (score_a - (1 - expected_h))

        _team_history[home].append((h_pts, row["fthg"], row["ftag"]))
        _team_history[away].append((a_pts, row["ftag"], row["fthg"]))

    print(f"[Predictor] История загружена: {len(df)} матчей, {len(_team_history)} команд")


def _form_stats(history):
    if not history:
        return 0.0, 0.0, 0.0
    pts = sum(h[0] for h in history) / len(history)
    scored = sum(h[1] for h in history) / len(history)
    conceded = sum(h[2] for h in history) / len(history)
    return pts, scored, conceded


def build_match_features(match: dict) -> pd.DataFrame:
    home = _normalize_team(match["home_team"])
    away = _normalize_team(match["away_team"])

    home_known = len(_team_history.get(home, [])) > 0
    away_known = len(_team_history.get(away, [])) > 0

    if home_known:
        h_pts, h_scored, h_conceded = _form_stats(_team_history[home])
        elo_h = _team_elo[home]
    else:
        h_pts, h_scored, h_conceded = FALLBACK_PTS, FALLBACK_SCORED, FALLBACK_CONCEDED
        elo_h = FALLBACK_ELO

    if away_known:
        a_pts, a_scored, a_conceded = _form_stats(_team_history[away])
        elo_a = _team_elo[away]
    else:
        a_pts, a_scored, a_conceded = FALLBACK_PTS, FALLBACK_SCORED, FALLBACK_CONCEDED
        elo_a = FALLBACK_ELO

    row = {
        "h_pts_last5": h_pts, "h_goals_scored_last5": h_scored, "h_goals_conceded_last5": h_conceded,
        "a_pts_last5": a_pts, "a_goals_scored_last5": a_scored, "a_goals_conceded_last5": a_conceded,
        "elo_h": elo_h, "elo_a": elo_a, "elo_diff": elo_h - elo_a,
        "psh": 2.5, "psd": 3.4, "psa": 3.0,
        "avgh": 2.5, "avgd": 3.4, "avga": 3.0,
    }
    return pd.DataFrame([row])[FEATURES]


def predict(match: dict, real_odds: dict = None) -> dict:
    ro = real_odds or {}

    oh_real = ro.get("home")
    od_real = ro.get("draw")
    oa_real = ro.get("away")
    o_over25_real = ro.get("over25")
    o_under25_real = ro.get("under25")

    # Если API не дал кэфы, подставляем базовые (средние), чтобы прогноз всё равно сформировался
    if not all([oh_real, od_real, oa_real, o_over25_real, o_under25_real]):
        print(f"[Predictor] Нет реальных кэфов для {match['home_team']} — {match['away_team']}. Используем fallback.")
        oh_real = oh_real or 2.10
        od_real = od_real or 3.40
        oa_real = oa_real or 3.20
        o_over25_real = o_over25_real or 1.85
        o_under25_real = o_under25_real or 1.95

    X = build_match_features(match)
    p_outcome = _outcome.predict_proba(X)[0]
    p_over25 = float(_over25.predict_proba(X)[0][1])
    p_btts = float(_btts.predict_proba(X)[0][1])
    p_cards = float(_cards.predict_proba(X)[0][1])

    p_home = float(p_outcome[0])
    p_draw = float(p_outcome[1])
    p_away = float(p_outcome[2])

    # ===== СТАВКА 1: ИСХОД =====
    outcome_options = [
        {"name": f"Победа {match['home_team']}", "prob": p_home, "odds": oh_real, "market": "outcome"},
        {"name": "Ничья", "prob": p_draw, "odds": od_real, "market": "outcome"},
        {"name": f"Победа {match['away_team']}", "prob": p_away, "odds": oa_real, "market": "outcome"},
    ]
    outcome_options = [o for o in outcome_options if MIN_ODDS <= o["odds"] <= MAX_ODDS]

    outcome_options = [
        o for o in outcome_options
        if (o["prob"] - (1 / o["odds"])) > -0.05
    ]

    bet1 = None
    if outcome_options:
        for o in outcome_options:
            implied = 1 / o["odds"]
            o["value"] = o["prob"] - implied
            o["score"] = o["prob"] * 0.5 + o["value"] * 0.5
        bet1 = max(outcome_options, key=lambda x: x["score"])

    # ===== СТАВКА 2: ТОТАЛ 2.5 =====
    total_options = [
        {"name": "Тотал больше 2.5", "prob": p_over25, "odds": o_over25_real, "market": "total"},
        {"name": "Тотал меньше 2.5", "prob": 1 - p_over25, "odds": o_under25_real, "market": "total"},
    ]
    total_options = [o for o in total_options if MIN_ODDS <= o["odds"] <= MAX_ODDS]

    total_options = [
        o for o in total_options
        if (o["prob"] - (1 / o["odds"])) > -0.05
    ]

    bet2 = None
    if total_options:
        for o in total_options:
            implied = 1 / o["odds"]
            o["value"] = o["prob"] - implied
            o["score"] = o["prob"] * 0.5 + o["value"] * 0.5
        bet2 = max(total_options, key=lambda x: x["score"])

    # ===== СОБИРАЕМ =====
    chosen = [b for b in [bet1, bet2] if b is not None]

    if not chosen:
        print(f"[Predictor] Нет ставок с приемлемым Edge для {match['home_team']} — {match['away_team']}.")
        return {"predictions": [], "simulation": {}}

    # ===== СИМУЛЯЦИЯ =====
    try:
        from simulator import simulate_match
        sim = simulate_match(
            p_home=p_home, p_draw=p_draw, p_away=p_away,
            p_over25=p_over25, p_btts=p_btts,
            p_corners_over=0.5, p_cards_over=p_cards,
            n_sims=100000,
        )
    except Exception as e:
        print(f"[Simulator] Ошибка: {e}")
        sim = {}

    return {
        "predictions": [
            {
                "bet_name": c["name"],
                "odds": round(float(c["odds"]), 2),
                "confidence": round(float(c["prob"]), 3),
                "market_prob": round(float(1 / c["odds"]), 3),
                "value": round(float(c["value"]), 3),
                "edge_pct": round(float(c["value"] * 100), 1),
                "score": round(float(c["score"]), 3),
                "source": "real" if real_odds and all(real_odds.values()) else "fallback",
                "value_class": (
                    "value-pos" if c["value"] > 0.03
                    else ("value-neutral" if c["value"] > 0 else "value-neg")
                ),
            }
            for c in chosen
        ],
        "simulation": sim,
    }


# ===== Единая точка получения кэфов =====
async def get_match_odds(league: str, home_team: str, away_team: str, match_date) -> dict:
    if not match_date:
        return {}

    if hasattr(match_date, "strftime"):
        date_str = match_date.strftime("%Y-%m-%d")
    else:
        date_str = str(match_date)[:10]

    try:
        return await get_api_football_odds(league, home_team, away_team, date_str)
    except Exception as e:
        print(f"[Odds] Ошибка get_api_football_odds: {e}")
        return {}