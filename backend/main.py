# backend/main.py
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select, desc, delete as sql_delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import io
import csv
import asyncio
import secrets

from database import init_db, get_db
from models import Match, Prediction
from schemas import MatchOut, PredictionOut, HistoryItem
from scheduler import start_scheduler, stop_scheduler, sync_matches
from predictor import predict, load_history_from_dataset, _team_history
from odds import get_match_odds
from api_football import get_api_football_odds

# ===== АВТОРИЗАЦИЯ =====
security = HTTPBasic()

AUTH_USER = "ac"
AUTH_PASS = "wellan"   # ⚠️ ПОМЕНЯЙ ПАРОЛЬ!


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, AUTH_USER)
    correct_password = secrets.compare_digest(credentials.password, AUTH_PASS)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ===== HEALTH CHECK + LIFESPAN =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    asyncio.create_task(sync_matches())

    DATASET_PATH = Path(__file__).parent.parent / "data" / "dataset.csv"
    if DATASET_PATH.exists():
        asyncio.create_task(_load_history_bg(str(DATASET_PATH)))

    yield
    stop_scheduler()


async def _load_history_bg(dataset_path):
    try:
        print(f"[Main] Загрузка истории в фоне...")
        await asyncio.to_thread(load_history_from_dataset, dataset_path)
        print(f"[Main] История загружена: {len(_team_history)} команд")
    except Exception as e:
        print(f"[Main] Ошибка загрузки истории: {e}")


app = FastAPI(title="Acwellan API", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== МАТЧИ (защищено) =====
@app.get("/api/matches", response_model=list[MatchOut])
async def get_matches(
    user: str = Depends(verify_credentials),
    league: str = "all",
    date: str = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(Match).where(Match.status == "upcoming")

    if league != "all":
        query = query.where(Match.league == league)

    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d")
            next_day = target.replace(hour=23, minute=59, second=59)
            query = query.where(Match.match_date.between(target, next_day))
        except ValueError:
            pass

    query = query.order_by(Match.match_date).limit(50)
    result = await db.execute(query)
    return result.scalars().all()


# ===== ПРОГНОЗ (защищено) =====
@app.post("/api/predict/{match_id}")
async def create_prediction(
    match_id: int,
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Матч не найден")

    real_odds = {}
    try:
        real_odds = await get_match_odds(match.league, match.home_team)
    except Exception as e:
        print(f"[Predict] Ошибка The Odds: {e}")

    api_fb_odds = {}
    try:
        date_str = match.match_date.strftime("%Y-%m-%d") if match.match_date else ""
        api_fb_odds = await get_api_football_odds(
            match.league, match.home_team, match.away_team, date_str
        )
    except Exception as e:
        print(f"[Predict] Ошибка API-Football: {e}")

    match_dict = {"home_team": match.home_team, "away_team": match.away_team}

    try:
        result = predict(match_dict, real_odds, api_fb_odds)
    except Exception as e:
        print(f"[Predictor] Ошибка: {e}")
        raise HTTPException(500, f"Ошибка модели: {e}")

    predictions = result["predictions"]
    simulation = result["simulation"]

    if not predictions:
        raise HTTPException(500, "Модель не смогла подобрать ставки")

    created = []
    for p in predictions:
        pred = Prediction(
            match_id=match.id,
            bet_name=p["bet_name"],
            odds=p["odds"],
            confidence=p["confidence"],
        )
        db.add(pred)
        created.append(pred)

    await db.commit()
    for p in created:
        await db.refresh(p)

    return {
        "match": {"id": match.id, "home_team": match.home_team, "away_team": match.away_team},
        "predictions": [
            {
                "id": p.id,
                "bet_name": p.bet_name,
                "odds": p.odds,
                "confidence": p.confidence,
                "value": p_conf["value"],
                "market_prob": p_conf["market_prob"],
                "edge_pct": p_conf["edge_pct"],
                "score": p_conf["score"],
                "source": p_conf.get("source", "model"),
                "value_class": p_conf["value_class"],
            }
            for p, p_conf in zip(created, predictions)
        ],
        "simulation": simulation,
        "refreshed_at": datetime.utcnow().isoformat(),
    }


@app.post("/api/predict-refresh/{match_id}")
async def refresh_prediction(
    match_id: int,
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Матч не найден")

    await db.execute(sql_delete(Prediction).where(Prediction.match_id == match_id))
    await db.commit()

    real_odds = {}
    try:
        real_odds = await get_match_odds(match.league, match.home_team)
    except Exception as e:
        print(f"[Refresh] Ошибка The Odds: {e}")

    api_fb_odds = {}
    try:
        date_str = match.match_date.strftime("%Y-%m-%d") if match.match_date else ""
        api_fb_odds = await get_api_football_odds(
            match.league, match.home_team, match.away_team, date_str
        )
    except Exception as e:
        print(f"[Refresh] Ошибка API-Football: {e}")

    match_dict = {"home_team": match.home_team, "away_team": match.away_team}

    try:
        result = predict(match_dict, real_odds, api_fb_odds)
    except Exception as e:
        raise HTTPException(500, f"Ошибка модели: {e}")

    predictions = result["predictions"]
    simulation = result["simulation"]

    if not predictions:
        raise HTTPException(500, "Модель не смогла подобрать ставки")

    created = []
    for p in predictions:
        pred = Prediction(
            match_id=match.id,
            bet_name=p["bet_name"],
            odds=p["odds"],
            confidence=p["confidence"],
        )
        db.add(pred)
        created.append(pred)

    await db.commit()
    for p in created:
        await db.refresh(p)

    return {
        "match": {"id": match.id, "home_team": match.home_team, "away_team": match.away_team},
        "predictions": [
            {
                "id": p.id,
                "bet_name": p.bet_name,
                "odds": p.odds,
                "confidence": p.confidence,
                "value": p_conf["value"],
                "market_prob": p_conf["market_prob"],
                "edge_pct": p_conf["edge_pct"],
                "score": p_conf["score"],
                "source": p_conf.get("source", "model"),
                "value_class": p_conf["value_class"],
            }
            for p, p_conf in zip(created, predictions)
        ],
        "simulation": simulation,
        "refreshed_at": datetime.utcnow().isoformat(),
    }


@app.post("/api/predict-batch")
async def predict_batch(
    user: str = Depends(verify_credentials),
    league: str = "all",
    date: str = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(Match).where(Match.status == "upcoming")

    if league != "all":
        query = query.where(Match.league == league)

    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d")
            next_day = target.replace(hour=23, minute=59, second=59)
            query = query.where(Match.match_date.between(target, next_day))
        except ValueError:
            pass

    query = query.order_by(Match.match_date).limit(30)
    result = await db.execute(query)
    matches = result.scalars().all()

    processed = 0
    skipped = 0
    created_total = 0

    for match in matches:
        existing = await db.execute(
            select(Prediction).where(Prediction.match_id == match.id)
        )
        if existing.scalars().first():
            skipped += 1
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
                print(f"[Batch] API-Football ошибка: {e}")

            pred_result = predict(
                {"home_team": match.home_team, "away_team": match.away_team},
                real_odds,
                api_fb_odds
            )

            if not pred_result["predictions"]:
                skipped += 1
                continue

            for p in pred_result["predictions"]:
                db.add(Prediction(
                    match_id=match.id,
                    bet_name=p["bet_name"],
                    odds=p["odds"],
                    confidence=p["confidence"],
                ))
                created_total += 1

            await db.commit()
            processed += 1
        except Exception as e:
            print(f"[Batch] Ошибка для match {match.id}: {e}")

    return {
        "total_matches": len(matches),
        "processed": processed,
        "skipped": skipped,
        "created_predictions": created_total,
    }


@app.get("/api/history")
async def get_history(
    user: str = Depends(verify_credentials),
    league: str = "all",
    result: str = "all",
    month: str = "all",
    db: AsyncSession = Depends(get_db)
):
    query = select(Prediction, Match).join(Match, Prediction.match_id == Match.id)

    if league != "all":
        query = query.where(Match.league == league)

    if result == "win":
        query = query.where(Prediction.result == "win")
    elif result == "lose":
        query = query.where(Prediction.result == "lose")
    elif result == "pending":
        query = query.where(Prediction.result.is_(None))

    if month != "all":
        try:
            query = query.where(func.strftime("%m.%Y", Match.match_date) == month)
        except ValueError:
            pass

    query = query.order_by(desc(Prediction.created_at)).limit(500)
    rows = await db.execute(query)

    grouped = {}
    for pred, match in rows.all():
        key = match.id
        if key not in grouped:
            grouped[key] = {"match": match, "predictions": []}
        grouped[key]["predictions"].append(pred)

    return [
        HistoryItem(
            match=MatchOut.model_validate(item["match"]),
            predictions=[PredictionOut.model_validate(p) for p in item["predictions"]],
        )
        for item in grouped.values()
    ]


@app.delete("/api/history/{match_id}")
async def delete_history(
    match_id: int,
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    await db.execute(sql_delete(Prediction).where(Prediction.match_id == match_id))
    await db.commit()
    return {"ok": True}


@app.patch("/api/prediction/{prediction_id}")
async def update_prediction_result(
    prediction_id: int,
    result: str,
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    if result not in ("win", "lose", "reset"):
        raise HTTPException(400, "result должен быть win / lose / reset")

    pred = await db.get(Prediction, prediction_id)
    if not pred:
        raise HTTPException(404, "Прогноз не найден")

    if result == "reset":
        pred.result = None
    else:
        pred.result = result

    await db.commit()
    return {"ok": True, "id": pred.id, "result": pred.result}


@app.get("/api/stats")
async def get_stats(
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    total_query = await db.execute(select(func.count(Prediction.id)))
    total = total_query.scalar() or 0

    win_query = await db.execute(select(func.count(Prediction.id)).where(Prediction.result == "win"))
    wins = win_query.scalar() or 0

    lose_query = await db.execute(select(func.count(Prediction.id)).where(Prediction.result == "lose"))
    loses = lose_query.scalar() or 0

    pending = total - wins - loses
    accuracy = (wins / (wins + loses) * 100) if (wins + loses) > 0 else 0

    return {"total": total, "wins": wins, "loses": loses, "pending": pending, "accuracy": round(accuracy, 1)}


@app.get("/api/monthly-results")
async def get_monthly_results(
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    BET_SIZE = 100.0
    result = await db.execute(select(Prediction, Match).join(Match, Prediction.match_id == Match.id))
    rows = result.all()

    months = defaultdict(lambda: {"total": 0, "wins": 0, "loses": 0, "bank": 0.0})
    overall = {"total": 0, "wins": 0, "loses": 0, "bank": 0.0}

    for pred, match in rows:
        if pred.result not in ("win", "lose") or match.match_date is None:
            continue

        label = match.match_date.strftime("%m.%Y")
        months[label]["total"] += 1
        overall["total"] += 1

        if pred.result == "win":
            profit = BET_SIZE * (pred.odds - 1)
            months[label]["wins"] += 1
            months[label]["bank"] += profit
            overall["wins"] += 1
            overall["bank"] += profit
        else:
            months[label]["loses"] += 1
            months[label]["bank"] -= BET_SIZE
            overall["loses"] += 1
            overall["bank"] -= BET_SIZE

    def sort_key(label):
        parts = label.split(".")
        return (int(parts[1]), int(parts[0]))

    monthly_list = []
    for label in sorted(months.keys(), key=sort_key, reverse=True):
        data = months[label]
        monthly_list.append({
            "month": label, "total": data["total"], "wins": data["wins"],
            "loses": data["loses"], "bank": round(data["bank"], 2),
        })

    accuracy = (overall["wins"] / overall["total"] * 100) if overall["total"] > 0 else 0

    return {
        "monthly": monthly_list,
        "overall": {
            "total": overall["total"], "wins": overall["wins"], "loses": overall["loses"],
            "bank": round(overall["bank"], 2), "accuracy": round(accuracy, 1),
        },
    }


@app.get("/api/league-stats")
async def get_league_stats(
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    BET_SIZE = 100.0
    result = await db.execute(select(Prediction, Match).join(Match, Prediction.match_id == Match.id))
    rows = result.all()

    leagues = defaultdict(lambda: {"league_name": "", "total": 0, "wins": 0, "loses": 0, "bank": 0.0})

    for pred, match in rows:
        if pred.result not in ("win", "lose"):
            continue

        key = match.league
        leagues[key]["league_name"] = match.league_name or key
        leagues[key]["total"] += 1

        if pred.result == "win":
            leagues[key]["wins"] += 1
            leagues[key]["bank"] += BET_SIZE * (pred.odds - 1)
        else:
            leagues[key]["loses"] += 1
            leagues[key]["bank"] -= BET_SIZE

    result_list = []
    for key, data in leagues.items():
        total = data["total"]
        accuracy = (data["wins"] / total * 100) if total > 0 else 0
        result_list.append({
            "league": key, "league_name": data["league_name"], "total": total,
            "wins": data["wins"], "loses": data["loses"],
            "accuracy": round(accuracy, 1), "bank": round(data["bank"], 2),
        })

    result_list.sort(key=lambda x: x["accuracy"], reverse=True)

    total_all = sum(r["total"] for r in result_list)
    wins_all = sum(r["wins"] for r in result_list)
    loses_all = sum(r["loses"] for r in result_list)
    bank_all = sum(r["bank"] for r in result_list)
    accuracy_all = (wins_all / total_all * 100) if total_all > 0 else 0

    return {
        "leagues": result_list,
        "overall": {
            "total": total_all, "wins": wins_all, "loses": loses_all,
            "bank": round(bank_all, 2), "accuracy": round(accuracy_all, 1),
        },
    }


@app.get("/api/bank-chart")
async def get_bank_chart(
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    BET_SIZE = 100.0
    result = await db.execute(select(Prediction, Match).join(Match, Prediction.match_id == Match.id))
    rows = result.all()

    months = defaultdict(lambda: {"bank": 0.0})

    for pred, match in rows:
        if pred.result not in ("win", "lose") or match.match_date is None:
            continue
        label = match.match_date.strftime("%m.%Y")
        if pred.result == "win":
            months[label]["bank"] += BET_SIZE * (pred.odds - 1)
        else:
            months[label]["bank"] -= BET_SIZE

    def sort_key(label):
        parts = label.split(".")
        return (int(parts[1]), int(parts[0]))

    sorted_months = sorted(months.keys(), key=sort_key)

    result_list = []
    cumulative = 0.0
    for label in sorted_months:
        cumulative += months[label]["bank"]
        result_list.append({
            "month": label, "bank": round(months[label]["bank"], 2),
            "cumulative": round(cumulative, 2),
        })

    return {"data": result_list, "total_bank": round(cumulative, 2)}


@app.get("/api/accuracy-30d")
async def get_accuracy_30d(
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    now = datetime.utcnow()
    month_ago = now - timedelta(days=30)

    result = await db.execute(select(Prediction, Match).join(Match, Prediction.match_id == Match.id))
    rows = result.all()

    d30 = {"total": 0, "wins": 0, "loses": 0, "bank": 0.0}
    dall = {"total": 0, "wins": 0, "loses": 0, "bank": 0.0}
    BET_SIZE = 100.0

    for pred, match in rows:
        if pred.result not in ("win", "lose") or match.match_date is None:
            continue

        profit = BET_SIZE * (pred.odds - 1) if pred.result == "win" else -BET_SIZE

        dall["total"] += 1
        if pred.result == "win":
            dall["wins"] += 1
        else:
            dall["loses"] += 1
        dall["bank"] += profit

        if match.match_date >= month_ago:
            d30["total"] += 1
            if pred.result == "win":
                d30["wins"] += 1
            else:
                d30["loses"] += 1
            d30["bank"] += profit

    def acc(d):
        return round((d["wins"] / d["total"] * 100) if d["total"] > 0 else 0, 1)

    return {
        "last_30_days": {"total": d30["total"], "wins": d30["wins"], "loses": d30["loses"], "bank": round(d30["bank"], 2), "accuracy": acc(d30)},
        "all_time": {"total": dall["total"], "wins": dall["wins"], "loses": dall["loses"], "bank": round(dall["bank"], 2), "accuracy": acc(dall)},
    }


@app.get("/api/edge-comparison")
async def get_edge_comparison(
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    BET_SIZE = 100.0
    result = await db.execute(select(Prediction, Match).join(Match, Prediction.match_id == Match.id))
    rows = result.all()

    groups = {
        "edge_gt_5": {"label": "Edge > 5%", "total": 0, "wins": 0, "loses": 0, "bank": 0.0, "edge_sum": 0.0},
        "edge_3_5":  {"label": "Edge 3–5%", "total": 0, "wins": 0, "loses": 0, "bank": 0.0, "edge_sum": 0.0},
        "edge_0_3":  {"label": "Edge 0–3%", "total": 0, "wins": 0, "loses": 0, "bank": 0.0, "edge_sum": 0.0},
        "edge_neg":  {"label": "Edge < 0%", "total": 0, "wins": 0, "loses": 0, "bank": 0.0, "edge_sum": 0.0},
    }

    overall = {"total": 0, "wins": 0, "loses": 0, "bank": 0.0, "edge_sum": 0.0}

    for pred, match in rows:
        if pred.result not in ("win", "lose"):
            continue

        if pred.odds and pred.odds > 0:
            edge = pred.confidence - (1 / pred.odds)
        else:
            edge = 0

        if edge > 0.05:
            key = "edge_gt_5"
        elif edge >= 0.03:
            key = "edge_3_5"
        elif edge >= 0:
            key = "edge_0_3"
        else:
            key = "edge_neg"

        if pred.result == "win":
            profit = BET_SIZE * (pred.odds - 1)
            groups[key]["wins"] += 1
            overall["wins"] += 1
        else:
            profit = -BET_SIZE
            groups[key]["loses"] += 1
            overall["loses"] += 1

        groups[key]["total"] += 1
        groups[key]["bank"] += profit
        groups[key]["edge_sum"] += edge

        overall["total"] += 1
        overall["bank"] += profit
        overall["edge_sum"] += edge

    result_list = []
    for key, data in groups.items():
        total = data["total"]
        accuracy = (data["wins"] / total * 100) if total > 0 else 0
        avg_edge = (data["edge_sum"] / total * 100) if total > 0 else 0
        result_list.append({
            "key": key, "label": data["label"], "total": total,
            "wins": data["wins"], "loses": data["loses"],
            "accuracy": round(accuracy, 1), "bank": round(data["bank"], 2),
            "avg_edge": round(avg_edge, 2),
        })

    overall_accuracy = (overall["wins"] / overall["total"] * 100) if overall["total"] > 0 else 0
    overall_avg_edge = (overall["edge_sum"] / overall["total"] * 100) if overall["total"] > 0 else 0
    overall_roi = (overall["bank"] / (overall["total"] * BET_SIZE) * 100) if overall["total"] > 0 else 0

    return {
        "groups": result_list,
        "overall": {
            "total": overall["total"], "wins": overall["wins"], "loses": overall["loses"],
            "bank": round(overall["bank"], 2), "accuracy": round(overall_accuracy, 1),
            "avg_edge": round(overall_avg_edge, 2), "roi": round(overall_roi, 1),
        },
    }


@app.get("/api/export-csv")
async def export_csv(
    user: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Prediction, Match).join(Match, Prediction.match_id == Match.id)
        .order_by(desc(Match.match_date))
    )
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Дата матча", "Лига", "Дома", "Гости", "Ставка", "Кэф", "Уверенность", "Value", "Результат", "Профит"])

    BET_SIZE = 100.0

    for pred, match in rows:
        profit = 0.0
        result_str = ""
        if pred.result == "win":
            profit = BET_SIZE * (pred.odds - 1)
            result_str = "WIN"
        elif pred.result == "lose":
            profit = -BET_SIZE
            result_str = "LOSE"
        else:
            result_str = "ОЖИДАНИЕ"

        value = pred.confidence - (1 / pred.odds) if pred.odds > 0 else 0

        writer.writerow([
            match.match_date.strftime("%d.%m.%Y %H:%M") if match.match_date else "",
            match.league_name or "", match.home_team or "", match.away_team or "",
            pred.bet_name or "", f"{pred.odds:.2f}", f"{pred.confidence * 100:.1f}%",
            f"{value * 100:+.1f}%", result_str,
            f"{profit:+.0f}$" if result_str != "ОЖИДАНИЕ" else "—",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=acwellan_history.csv"}
    )