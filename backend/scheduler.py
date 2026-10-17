# backend/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from datetime import datetime, timedelta
import asyncio
from database import async_session
from models import Match, Prediction
from sportsdb import fetch_matches, LEAGUES

scheduler = AsyncIOScheduler()


async def sync_matches():
    """Обновляет матчи из Football-Data.org."""
    print("[Scheduler] Синхронизация матчей...")
    async with async_session() as session:
        for i, league_key in enumerate(LEAGUES):
            matches = await fetch_matches(league_key)
            for m in matches:
                await upsert_match(session, m)
            if i < len(LEAGUES) - 1:
                await asyncio.sleep(12)
        await session.commit()
    print("[Scheduler] Синхронизация завершена.")


async def sync_match_stats():
    """Получает углы и карточки для завершённых матчей через API-Football."""
    from api_football import get_api_football_stats

    print("[Scheduler] Синхронизация статистики матчей...")
    async with async_session() as session:
        result = await session.execute(
            select(Match).where(
                Match.status == "finished",
                Match.home_corners.is_(None)
            )
        )
        matches = result.scalars().all()

        for match in matches:
            try:
                date_str = match.match_date.strftime("%Y-%m-%d") if match.match_date else ""
                stats = await get_api_football_stats(
                    match.league, match.home_team, match.away_team, date_str
                )
                if stats:
                    match.home_corners = stats["home_corners"]
                    match.away_corners = stats["away_corners"]
                    match.home_cards = stats["home_cards"]
                    match.away_cards = stats["away_cards"]
                    print(f"[Stats] {match.home_team} — {match.away_team}: "
                          f"углы {stats['total_corners']}, карточки {stats['total_cards']}")
            except Exception as e:
                print(f"[Stats] Ошибка для {match.id}: {e}")

        await session.commit()
    print("[Scheduler] Статистика обновлена.")


async def upsert_match(session, data: dict):
    """Добавить матч, если его нет; обновить, если есть."""
    existing = await session.execute(
        select(Match).where(Match.event_id == data["event_id"])
    )
    match = existing.scalar_one_or_none()

    if match:
        match.home_score = data["home_score"]
        match.away_score = data["away_score"]
        match.status = data["status"]
    else:
        session.add(Match(**data))


async def settle_predictions():
    """Проверяет завершённые матчи и проставляет WIN/LOSE прогнозам.
    Прогнозы по углам и карточкам без данных остаются в ОЖИДАНИИ (None).
    """
    print("[Scheduler] Проверка прогнозов...")
    async with async_session() as session:
        result = await session.execute(
            select(Match).where(Match.status == "finished")
        )
        matches = result.scalars().all()

        for match in matches:
            preds = await session.execute(
                select(Prediction).where(
                    Prediction.match_id == match.id,
                    Prediction.result.is_(None)
                )
            )
            predictions = preds.scalars().all()

            for pred in predictions:
                result_value = evaluate_bet(pred.bet_name, match)
                if result_value is not None:
                    pred.result = result_value

        await session.commit()
    print("[Scheduler] Проверка завершена.")


def evaluate_bet(bet_name: str, match: Match):
    """
    Оценивает ставку.
    Возвращает 'win' / 'lose' / None.
    None = нет данных (углы/карточки без статистики) — остаётся ОЖИДАНИЕ.
    """
    h = match.home_score or 0
    a = match.away_score or 0
    total = h + a

    name = bet_name.lower()

    # П1 / Х / П2
    if "победа" in name:
        if match.home_team.lower() in name:
            return "win" if h > a else "lose"
        elif match.away_team.lower() in name:
            return "win" if a > h else "lose"
        return "lose"

    if "ничья" in name:
        return "win" if h == a else "lose"

    # Тоталы
    if "тотал больше" in name or "тб" in name:
        import re
        m = re.search(r"(\d+\.?\d*)", bet_name)
        if m:
            line = float(m.group(1))
            return "win" if total > line else "lose"
        return "lose"

    if "тотал меньше" in name or "тм" in name:
        import re
        m = re.search(r"(\d+\.?\d*)", bet_name)
        if m:
            line = float(m.group(1))
            return "win" if total < line else "lose"
        return "lose"

    # Обе забьют
    if "обе забьют" in name:
        return "win" if (h > 0 and a > 0) else "lose"
    if "обе не забьют" in name:
        return "win" if (h == 0 or a == 0) else "lose"

    # Углы — только если есть данные
    if "угловые" in name:
        import re
        m = re.search(r"(\d+\.?\d*)", bet_name)
        if m and match.home_corners is not None:
            line = float(m.group(1))
            total_corners = (match.home_corners or 0) + (match.away_corners or 0)
            return "win" if total_corners > line else "lose"
        return None

    # Карточки — только если есть данные
    if "карточки" in name:
        import re
        m = re.search(r"(\d+\.?\d*)", bet_name)
        if m and match.home_cards is not None:
            line = float(m.group(1))
            total_cards = (match.home_cards or 0) + (match.away_cards or 0)
            return "win" if total_cards > line else "lose"
        return None

    return "lose"


async def auto_predict_all():
    """Автоматически делает прогнозы на матчи ближайших 24 часов."""
    print("[Scheduler] Авто-прогнозы...")
    from predictor import predict
    from odds import get_match_odds
    from api_football import get_api_football_odds

    async with async_session() as session:
        now = datetime.utcnow()
        tomorrow = now + timedelta(days=1)

        result = await session.execute(
            select(Match).where(
                Match.status == "upcoming",
                Match.match_date.between(now, tomorrow)
            )
        )
        matches = result.scalars().all()

        for match in matches:
            existing = await session.execute(
                select(Prediction).where(Prediction.match_id == match.id)
            )
            if existing.scalars().first():
                continue

            try:
                real_odds = await get_match_odds(match.league, match.home_team)

                api_fb_odds = {}
                try:
                    date_str = match.match_date.strftime("%Y-%m-%d") if match.match_date else ""
                    api_fb_odds = await get_api_football_odds(
                        match.league, match.home_team, match.away_team, date_str
                    )
                except Exception as e:
                    print(f"[Auto] API-Football ошибка: {e}")

                pred_result = predict(
                    {"home_team": match.home_team, "away_team": match.away_team},
                    real_odds,
                    api_fb_odds
                )
                for p in pred_result["predictions"]:
                    session.add(Prediction(
                        match_id=match.id,
                        bet_name=p["bet_name"],
                        odds=p["odds"],
                        confidence=p["confidence"],
                    ))
                await session.commit()
                print(f"[Auto] Прогноз для {match.home_team} — {match.away_team}")
            except Exception as e:
                print(f"[Auto] Ошибка для {match.id}: {e}")

    print("[Scheduler] Авто-прогнозы завершены.")


async def add_finished_to_dataset():
    """Добавляет завершённые матчи из БД в dataset.csv."""
    import pandas as pd
    import os

    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "dataset.csv")
    if not os.path.exists(data_path):
        print(f"[Retrain] dataset.csv не найден: {data_path}")
        return

    df = pd.read_csv(data_path)
    existing_ids = set(df["date"].astype(str) + "_" + df["home_team"] + "_" + df["away_team"])

    async with async_session() as session:
        result = await session.execute(
            select(Match).where(Match.status == "finished")
        )
        matches = result.scalars().all()

    added = 0
    new_rows = []
    for m in matches:
        if m.home_score is None or m.away_score is None:
            continue
        if m.match_date is None:
            continue

        key = f"{m.match_date.isoformat()}_{m.home_team}_{m.away_team}"
        if key in existing_ids:
            continue

        ftr = "H" if m.home_score > m.away_score else ("A" if m.away_score > m.home_score else "D")
        new_rows.append({
            "date": m.match_date,
            "league": m.league,
            "home_team": m.home_team,
            "away_team": m.away_team,
            "h_pts_last5": 0.0, "h_goals_scored_last5": 0.0, "h_goals_conceded_last5": 0.0,
            "a_pts_last5": 0.0, "a_goals_scored_last5": 0.0, "a_goals_conceded_last5": 0.0,
            "elo_h": 1500, "elo_a": 1500, "elo_diff": 0,
            "psh": 2.5, "psd": 3.4, "psa": 3.0,
            "avgh": 2.5, "avgd": 3.4, "avga": 3.0,
            "fthg": m.home_score, "ftag": m.away_score, "ftr": ftr,
            "hy": m.home_cards or 0, "ay": m.away_cards or 0,
            "hc": m.home_corners or 0, "ac": m.away_corners or 0,
        })
        added += 1

    if added > 0:
        new_df = pd.DataFrame(new_rows)
        df = pd.concat([df, new_df], ignore_index=True)
        df.to_csv(data_path, index=False)
        print(f"[Retrain] Добавлено {added} новых матчей в dataset.csv")
    else:
        print("[Retrain] Новых матчей нет")


async def retrain_models():
    """Раз в 30 дней: обновить датасет, пересобрать признаки, переобучить модели."""
    print("[Scheduler] Переобучение моделей...")
    import subprocess
    import sys
    import os

    backend_dir = os.path.dirname(__file__)

    try:
        await add_finished_to_dataset()
    except Exception as e:
        print(f"[Retrain] Ошибка add_finished: {e}")

    try:
        result = subprocess.run(
            [sys.executable, "prepare_data.py"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            print(f"[Retrain] prepare_data.py упал: {result.stderr[:500]}")
            return
        print("[Retrain] dataset.csv пересобран")
    except Exception as e:
        print(f"[Retrain] Ошибка prepare_data: {e}")
        return

    try:
        result = subprocess.run(
            [sys.executable, "train.py"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            print(f"[Retrain] train.py упал: {result.stderr[:500]}")
            return
        print("[Retrain] Модели переобучены")
        print(result.stdout[-800:])
    except Exception as e:
        print(f"[Retrain] Ошибка train: {e}")


def start_scheduler():
    scheduler.add_job(sync_matches, "interval", minutes=15, id="sync_matches")
    scheduler.add_job(sync_match_stats, "interval", minutes=30, id="sync_stats")
    scheduler.add_job(settle_predictions, "interval", minutes=5, id="settle_predictions")
    scheduler.add_job(auto_predict_all, "interval", hours=24, id="auto_predict")
    scheduler.add_job(retrain_models, "interval", days=30, id="retrain")
    scheduler.start()
    print("[Scheduler] Планировщик запущен.")
    print("[Scheduler] sync_matches — каждые 15 минут")
    print("[Scheduler] settle_predictions — каждые 5 минут")
    print("[Scheduler] sync_match_stats — каждые 30 минут")


def stop_scheduler():
    scheduler.shutdown()
    print("[Scheduler] Планировщик остановлен.")