# backend/simulator.py
"""
Монте-Карло симуляция матча.
λ вычисляются ПЛАВНО из вероятностей модели — поэтому симуляция
разная для разных матчей.
"""
import numpy as np
from collections import Counter


def simulate_match(p_home, p_draw, p_away, p_over25, p_btts,
                   p_corners_over, p_cards_over, n_sims=100000, seed=42):
    rng = np.random.default_rng(seed)

    probs = np.array([p_home, p_draw, p_away], dtype=float)
    probs = probs / probs.sum()

    outcomes = rng.choice([0, 1, 2], size=n_sims, p=probs)

    lam_home, lam_away = _fit_lambdas(p_home, p_draw, p_away, p_over25)

    home_goals = rng.poisson(lam_home, size=n_sims)
    away_goals = rng.poisson(lam_away, size=n_sims)

    # Приводим счёт в соответствие с исходом
    for i in range(n_sims):
        out = outcomes[i]
        h, a = home_goals[i], away_goals[i]
        if out == 0 and h <= a:
            home_goals[i] = a + 1
        elif out == 1 and h != a:
            home_goals[i] = a
        elif out == 2 and h >= a:
            away_goals[i] = h + 1

    total_goals = home_goals + away_goals

    outcomes_count = Counter(outcomes.tolist())
    outcomes_dist = {
        "home_win": outcomes_count[0] / n_sims,
        "draw": outcomes_count[1] / n_sims,
        "away_win": outcomes_count[2] / n_sims,
    }

    score_pairs = list(zip(home_goals.tolist(), away_goals.tolist()))
    score_counter = Counter(score_pairs)
    top_scores = [
        {"score": f"{h}:{a}", "prob": round(c / n_sims, 4)}
        for (h, a), c in score_counter.most_common(5)
    ]

    over_1_5 = float(np.mean(total_goals > 1.5))
    over_2_5 = float(np.mean(total_goals > 2.5))
    over_3_5 = float(np.mean(total_goals > 3.5))
    under_2_5 = 1 - over_2_5
    btts_yes = float(np.mean((home_goals > 0) & (away_goals > 0)))

    return {
        "n_sims": n_sims,
        "outcomes": outcomes_dist,
        "top_scores": top_scores,
        "over_1_5": round(over_1_5, 4),
        "over_2_5": round(over_2_5, 4),
        "over_3_5": round(over_3_5, 4),
        "under_2_5": round(under_2_5, 4),
        "btts_yes": round(btts_yes, 4),
        "btts_no": round(1 - btts_yes, 4),
        "corners_over": round(p_corners_over, 4),
        "cards_over": round(p_cards_over, 4),
    }


def _fit_lambdas(p_home, p_draw, p_away, p_over25):
    """
    ПЛАВНЫЙ подбор λ из вероятностей.
    Линейная зависимость — симуляция разная для разных матчей.
    """
    # Средний тотал: линейно от P(>2.5)
    # 0.30 → 2.2 гола, 0.70 → 3.5 гола
    total_avg = 2.2 + (p_over25 - 0.30) * (3.5 - 2.2) / (0.70 - 0.30)
    total_avg = max(1.8, min(4.5, total_avg))

    # Разница в силе: чем больше разрыв, тем сильнее хозяева
    diff = p_home - p_away
    ratio = 0.5 + diff * 0.35
    ratio = max(0.25, min(0.75, ratio))

    lam_home = total_avg * ratio
    lam_away = total_avg * (1 - ratio)

    return max(0.3, lam_home), max(0.3, lam_away)