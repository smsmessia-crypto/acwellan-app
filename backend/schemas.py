# backend/schemas.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class MatchOut(BaseModel):
    id: int
    event_id: str
    league: str
    league_name: str
    home_team: str
    away_team: str
    match_date: datetime
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    home_corners: Optional[int] = None
    away_corners: Optional[int] = None
    home_cards: Optional[int] = None
    away_cards: Optional[int] = None
    status: str

    class Config:
        from_attributes = True


class PredictionOut(BaseModel):
    id: int
    match_id: int
    bet_name: str
    odds: float
    confidence: float
    result: Optional[str] = None

    class Config:
        from_attributes = True


class HistoryItem(BaseModel):
    match: MatchOut
    predictions: List[PredictionOut]