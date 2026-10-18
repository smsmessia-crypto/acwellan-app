# backend/models.py
from sqlalchemy import Column, Integer, String, DateTime, Float
from datetime import datetime
from database import Base


class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, unique=True, index=True)
    league = Column(String)
    league_name = Column(String)
    home_team = Column(String)
    away_team = Column(String)
    match_date = Column(DateTime)
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    status = Column(String, default="upcoming")
    home_corners = Column(Integer, nullable=True)
    away_corners = Column(Integer, nullable=True)
    home_cards = Column(Integer, nullable=True)
    away_cards = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, index=True)
    bet_name = Column(String)
    odds = Column(Float)
    confidence = Column(Float)
    result = Column(String, nullable=True)
    user_id = Column(String, index=True, nullable=True)  # <-- НОВОЕ ПОЛЕ
    created_at = Column(DateTime, default=datetime.utcnow)