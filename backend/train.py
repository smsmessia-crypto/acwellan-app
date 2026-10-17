# backend/train.py
import os
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss

BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "..", "data", "dataset.csv")
MODELS_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

FEATURES = [
    "h_pts_last5", "h_goals_scored_last5", "h_goals_conceded_last5",
    "a_pts_last5", "a_goals_scored_last5", "a_goals_conceded_last5",
    "elo_h", "elo_a", "elo_diff",
    "psh", "psd", "psa", "avgh", "avgd", "avga",
]


def load_data():
    df = pd.read_csv(DATA_PATH)
    df["date"] = pd.to_datetime(df["date"])
    df["total_goals"] = df["fthg"] + df["ftag"]

    # Существующие таргеты
    df["over_2_5"] = (df["total_goals"] > 2.5).astype(int)
    df["btts"] = ((df["fthg"] > 0) & (df["ftag"] > 0)).astype(int)

    # Новые таргеты
    df["over_1_5"] = (df["total_goals"] > 1.5).astype(int)
    df["over_3_5"] = (df["total_goals"] > 3.5).astype(int)

    # Углы / карточки
    df["total_corners"] = df["hc"].fillna(0) + df["ac"].fillna(0)
    df["corners_over_9_5"] = (df["total_corners"] > 9.5).astype(int)
    df["total_cards"] = df["hy"].fillna(0) + df["ay"].fillna(0)
    df["cards_over_3_5"] = (df["total_cards"] > 3.5).astype(int)

    df["outcome"] = df["ftr"].map({"H": 0, "D": 1, "A": 2})
    df[FEATURES] = df[FEATURES].fillna(df[FEATURES].median(numeric_only=True))
    return df


def split_by_season(df):
    df = df.copy()
    df["season"] = df["date"].apply(lambda d: f"{d.year}/{d.year + 1}" if d.month >= 7 else f"{d.year - 1}/{d.year}")
    train = df[df["season"] < "2025/2026"]
    test = df[df["season"] == "2025/2026"]
    print(f"Train: {len(train)}, Test: {len(test)}")
    return train, test


def train_outcome(train, test):
    print("\n===== Исход (H/D/A) =====")
    X_train, y_train = train[FEATURES], train["outcome"]
    X_test, y_test = test[FEATURES], test["outcome"]

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        objective="multi:softprob", num_class=3, eval_metric="mlogloss", verbosity=0,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)
    acc = accuracy_score(y_test, preds)
    print(f"Accuracy: {acc:.3f}")
    print(f"Средние вероятности: H={probs[:,0].mean()*100:.1f}%  D={probs[:,1].mean()*100:.1f}%  A={probs[:,2].mean()*100:.1f}%")

    path = os.path.join(MODELS_DIR, "outcome_model.json")
    model.save_model(path)
    print(f"[✓] {path}")


def train_model(train, test, target_col, label, filename):
    print(f"\n===== {label} =====")
    X_train, y_train = train[FEATURES], train[target_col]
    X_test, y_test = test[FEATURES], test[target_col]

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        objective="binary:logistic", eval_metric="logloss", verbosity=0,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)[:, 1]
    acc = accuracy_score(y_test, preds)
    ll = log_loss(y_test, probs)
    print(f"Accuracy: {acc:.3f}   LogLoss: {ll:.3f}")
    print(f"Средняя вероятность: {probs.mean()*100:.1f}%")

    path = os.path.join(MODELS_DIR, filename)
    model.save_model(path)
    print(f"[✓] {path}")


def main():
    print("=" * 50)
    print("Обучение моделей")
    print("=" * 50)

    df = load_data()
    print(f"Всего матчей: {len(df)}")

    from collections import Counter
    dist = Counter(df["ftr"].tolist())
    total = sum(dist.values())
    print("Распределение исходов:")
    for k in ["H", "D", "A"]:
        print(f"  {k}: {dist.get(k, 0)} ({dist.get(k, 0)/total*100:.1f}%)")

    train, test = split_by_season(df)

    train_outcome(train, test)
    train_model(train, test, "over_1_5", "Тотал >1.5", "over15_model.json")
    train_model(train, test, "over_2_5", "Тотал >2.5", "over25_model.json")
    train_model(train, test, "over_3_5", "Тотал >3.5", "over35_model.json")
    train_model(train, test, "btts", "Обе забьют", "btts_model.json")
    train_model(train, test, "corners_over_9_5", "Углы >9.5", "corners_model.json")
    train_model(train, test, "cards_over_3_5", "Карточки >3.5", "cards_model.json")

    print("\n" + "=" * 50)
    print("Готово")
    print("=" * 50)


if __name__ == "__main__":
    main()