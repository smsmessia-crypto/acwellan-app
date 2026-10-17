# backend/prepare_data.py
import os
import glob
import pandas as pd
from collections import defaultdict, deque

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUTPUT = os.path.join(DATA_DIR, "dataset.csv")

LEAGUE_FILES = {
    "E0": "EPL", "SP1": "LaLiga", "D1": "Bundesliga",
    "I1": "SerieA", "F1": "Ligue1",
}

ELO_START = 1500
ELO_K = 20


def elo_update(elo_h, elo_a, result_home):
    expected_h = 1 / (1 + 10 ** ((elo_a - elo_h) / 400))
    expected_a = 1 - expected_h
    if result_home == "H":
        score_h, score_a = 1.0, 0.0
    elif result_home == "A":
        score_h, score_a = 0.0, 1.0
    else:
        score_h, score_a = 0.5, 0.5
    return elo_h + ELO_K * (score_h - expected_h), elo_a + ELO_K * (score_a - expected_a)


def load_all_matches():
    frames = []
    for prefix, league_name in LEAGUE_FILES.items():
        pattern = os.path.join(DATA_DIR, f"{prefix}_*.csv")
        files = sorted(glob.glob(pattern))
        for path in files:
            try:
                df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")

            # Добавили HY, AY, HC, AC (карточки и углы)
            needed = [
                "Date", "HomeTeam", "AwayTeam",
                "FTHG", "FTAG", "FTR",
                "HY", "AY", "HC", "AC",
                "PSH", "PSD", "PSA",
                "AvgH", "AvgD", "AvgA",
            ]
            df = df[[c for c in needed if c in df.columns]].copy()
            df["league"] = league_name
            frames.append(df)
            print(f"[+] {os.path.basename(path)}: {len(df)} строк")

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.dropna(subset=["FTHG", "FTAG", "FTR"])
    all_df["FTHG"] = all_df["FTHG"].astype(int)
    all_df["FTAG"] = all_df["FTAG"].astype(int)
    all_df["Date"] = pd.to_datetime(all_df["Date"], dayfirst=True, errors="coerce")
    all_df = all_df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    print(f"\nВсего матчей: {len(all_df)}")
    return all_df


def build_features(df):
    team_history = defaultdict(lambda: deque(maxlen=5))
    elo = defaultdict(lambda: ELO_START)
    rows = []

    for _, match in df.iterrows():
        home, away = match["HomeTeam"], match["AwayTeam"]

        def form_stats(history):
            if not history:
                return 0.0, 0.0, 0.0
            pts = sum(h[0] for h in history) / len(history)
            scored = sum(h[1] for h in history) / len(history)
            conceded = sum(h[2] for h in history) / len(history)
            return pts, scored, conceded

        h_pts, h_scored, h_conceded = form_stats(team_history[home])
        a_pts, a_scored, a_conceded = form_stats(team_history[away])
        elo_h, elo_a = elo[home], elo[away]

        row = {
            "date": match["Date"], "league": match["league"],
            "home_team": home, "away_team": away,
            "h_pts_last5": h_pts, "h_goals_scored_last5": h_scored, "h_goals_conceded_last5": h_conceded,
            "a_pts_last5": a_pts, "a_goals_scored_last5": a_scored, "a_goals_conceded_last5": a_conceded,
            "elo_h": elo_h, "elo_a": elo_a, "elo_diff": elo_h - elo_a,
            "psh": match.get("PSH"), "psd": match.get("PSD"), "psa": match.get("PSA"),
            "avgh": match.get("AvgH"), "avgd": match.get("AvgD"), "avga": match.get("AvgA"),
            "fthg": match["FTHG"], "ftag": match["FTAG"], "ftr": match["FTR"],
            "hy": match.get("HY"), "ay": match.get("AY"),
            "hc": match.get("HC"), "ac": match.get("AC"),
        }
        rows.append(row)

        if match["FTR"] == "H":
            h_pts_match, a_pts_match = 3, 0
        elif match["FTR"] == "A":
            h_pts_match, a_pts_match = 0, 3
        else:
            h_pts_match, a_pts_match = 1, 1

        team_history[home].append((h_pts_match, match["FTHG"], match["FTAG"]))
        team_history[away].append((a_pts_match, match["FTAG"], match["FTHG"]))

        new_h, new_a = elo_update(elo_h, elo_a, match["FTR"])
        elo[home], elo[away] = new_h, new_a

    return pd.DataFrame(rows)


def main():
    print("=" * 50)
    print("Подготовка датасета")
    print("=" * 50)
    df = load_all_matches()
    if len(df) == 0:
        print("[!] Нет данных.")
        return
    print("\nСчитаем признаки...")
    features = build_features(df)
    features.to_csv(OUTPUT, index=False)
    print(f"\n[✓] Сохранено: {OUTPUT}")
    print(f"    Строк: {len(features)}")


if __name__ == "__main__":
    main()
