# backend/odds.py
import os
import numpy as np
import pandas as pd
import xgboost as xgb
from collections import defaultdict, deque

from odds_api import get_real_odds

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
    if not name: return ""
    parts = []
    for w in name.lower().strip().split():
        w = w.replace(".", "").replace(",", "").strip()
        if w in SKIP_WORDS or w.isdigit(): continue
        parts.append(w)
    return " ".join(parts) if parts else name.lower().strip()

def load_history_from_dataset(dataset_path):
    global _team_history, _team_elo
    df = pd.read_csv(dataset_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    for _, row in df.iterrows():
        home, away = _normalize_team(row["home_team"]), _normalize_team(row["away_team"])
        elo_h, elo_a = _team_elo[home], _team_elo[away]
        expected_h = 1 / (1 + 10 ** ((elo_a - elo_h) / 400))
        if row["ftr"] == "H": score_h, score_a, h_pts, a_pts = 1.0, 0.0, 3, 0
        elif row["ftr"] == "A": score_h, score_a, h_pts, a_pts = 0.0, 1.0, 0, 3
        else: score_h, score_a, h_pts, a_pts = 0.5, 0.5, 1, 1
        _team_elo[home] = elo_h + ELO_K * (score_h - expected_h)
        _team_elo[away] = elo_a + ELO_K * (score_a - (1 - expected_h))
        _team_history[home].append((h_pts, row["fthg"], row["ftag"]))
        _team_history[away].append((a_pts, row["ftag"], row["fthg"]))
    print(f"[Predictor] История загружена: {len(df)} матчей.")

def _form_stats(history):
    if not history: return 0.0, 0.0, 0.0
    return (sum(h[0] for h in history) / len(history), 
            sum(h[1] for h in history) / len(history), 
            sum(h[2] for h in history) / len(history))

def build_match_features(match: dict) -> pd.DataFrame:
    home, away = _normalize_team(match["home_team"]), _normalize_team(match["away_team"])
    if len(_team_history.get(home, [])) > 0:
        h_pts, h_scored, h_conceded = _form_stats(_team_history[home])
        elo_h = _team_elo[home]
    else:
        h_pts, h_scored, h_conceded, elo_h = FALLBACK_PTS, FALLBACK_SCORED, FALLBACK_CONCEDED, FALLBACK_ELO
    if len(_team_history.get(away, [])) > 0:
        a_pts, a_scored, a_conceded = _form_stats(_team_history[away])
        elo_a = _team_elo[away]
    else:
        a_pts, a_scored, a_conceded, elo_a = FALLBACK_PTS, FALLBACK_SCORED, FALLBACK_CONCEDED, FALLBACK_ELO

    row = {
        "h_pts_last5": h_pts, "h_goals_scored_last5": h_scored, "h_goals_conceded_last5": h_conceded,
        "a_pts_last5": a_pts, "a_goals_scored_last5": a_scored, "a_goals_conceded_last5": a_conceded,
        "elo_h": elo_h, "elo_a": elo_a, "elo_diff": elo_h - elo_a,
        "psh": 2.5, "psd": 3.4, "psa": 3.0, "avgh": 2.5, "avgd": 3.4, "avga": 3.0,
    }
    return pd.DataFrame([row])[FEATURES]

def predict(match: dict, real_odds: dict = None) -> dict:
    ro = real_odds or {}
    
    # Если API не дал кэфы, подставляем базовые, чтобы фронтенд не падал с ошибкой
    if not all([ro.get("home"), ro.get("draw"), ro.get("away"), ro.get("over25"), ro.get("under25")]):
        print(f"[Predictor] Нет реальных кэфов для {match['home_team']} — {match['away_team']}. Используем fallback.")
        ro["home"] = ro.get("home") or 2.10
        ro["draw"] = ro.get("draw") or 3.40
        ro["away"] = ro.get("away") or 3.20
        ro["over25"] = ro.get("over25") or 1.85
        ro["under25"] = ro.get("under25") or 1.95

    X = build_match_features(match)
    p_outcome = _outcome.predict_proba(X)[0]
    p_over25 = float(_over25.predict_proba(X)[0][1])
    p_btts = float(_btts.predict_proba(X)[0][1])
    p_cards = float(_cards.predict_proba(X)[0][1])
    p_home, p_draw, p_away = float(p_outcome[0]), float(p_outcome[1]), float(p_outcome[2])

    # Ищем лучший исход
    outcome_opts = [
        {"name": f"Победа {match['home_team']}", "prob": p_home, "odds": ro["home"]},
        {"name": "Ничья", "prob": p_draw, "odds": ro["draw"]},
        {"name": f"Победа {match['away_team']}", "prob": p_away, "odds": ro["away"]},
    ]
    for o in outcome_opts:
        o["value"] = o["prob"] - (1 / o["odds"])
        o["score"] = o["prob"] * 0.5 + o["value"] * 0.5
    bet1 = max(outcome_opts, key=lambda x: x["score"])

    # Ищем лучший тотал
    total_opts = [
        {"name": "Тотал больше 2.5", "prob": p_over25, "odds": ro["over25"]},
        {"name": "Тотал меньше 2.5", "prob": 1 - p_over25, "odds": ro["under25"]},
    ]
    for o in total_opts:
        o["value"] = o["prob"] - (1 / o["odds"])
        o["score"] = o["prob"] * 0.5 + o["value"] * 0.5
    bet2 = max(total_opts, key=lambda x: x["score"])

    chosen = [bet1, bet2]

    try:
        from simulator import simulate_match
        sim = simulate_match(
            p_home=p_home, p_draw=p_draw, p_away=p_away,
            p_over25=p_over25, p_btts=p_btts, p_corners_over=0.5, p_cards_over=p_cards, n_sims=100000
        )
    except Exception: sim = {}

    return {
        "predictions": [
            {
                "bet_name": c["name"], "odds": round(float(c["odds"]), 2),
                "confidence": round(float(c["prob"]), 3), "market_prob": round(float(1 / c["odds"]), 3),
                "value": round(float(c["value"]), 3), "edge_pct": round(float(c["value"] * 100), 1),
                "score": round(float(c["score"]), 3), "source": "real" if real_odds and all(real_odds.values()) else "fallback",
                "value_class": "value-pos" if c["value"] > 0.03 else ("value-neutral" if c["value"] > 0 else "value-neg"),
            } for c in chosen
        ], "simulation": sim,
    }

async def get_match_odds(league: str, home_team: str, away_team: str, match_date) -> dict:
    try: return await get_real_odds(league, home_team, away_team)
    except Exception as e:
        print(f"[Odds] Ошибка: {e}")
        return {}