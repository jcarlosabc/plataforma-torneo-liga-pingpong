from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    avatar = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    player1_id = Column(Integer, ForeignKey("players.id"))
    player2_id = Column(Integer, ForeignKey("players.id"))
    player1 = relationship("Player", foreign_keys=[player1_id])
    player2 = relationship("Player", foreign_keys=[player2_id])
    created_at = Column(DateTime, default=datetime.utcnow)


class Tournament(Base):
    __tablename__ = "tournaments"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)   # "individual" | "doubles"
    status = Column(String, default="draft")  # "draft" | "active" | "completed"
    created_at = Column(DateTime, default=datetime.utcnow)


class TournamentParticipant(Base):
    __tablename__ = "tournament_participants"
    id = Column(Integer, primary_key=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"))
    participant_id = Column(Integer, nullable=False)


class League(Base):
    __tablename__ = "leagues"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)   # "individual" | "doubles"
    status = Column(String, default="active")  # "active" | "completed"
    double_rr = Column(Boolean, default=False)   # True = ida y vuelta
    matches_per_jornada = Column(Integer, default=1)  # 1 = todos en una jornada, 2 = 2 partidos por jugador por jornada
    created_at = Column(DateTime, default=datetime.utcnow)


class LeagueParticipant(Base):
    __tablename__ = "league_participants"
    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, ForeignKey("leagues.id"))
    participant_id = Column(Integer, nullable=False)


class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=True)
    round = Column(Integer, default=1)
    match_in_round = Column(Integer, default=1)
    participant1_id = Column(Integer, nullable=True)
    participant2_id = Column(Integer, nullable=True)
    score1 = Column(Integer, default=0)
    score2 = Column(Integer, default=0)
    winner_id = Column(Integer, nullable=True)
    status = Column(String, default="pending")  # "pending" | "completed"
    is_bye = Column(Boolean, default=False)
    is_third_place = Column(Boolean, default=False)
    next_match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    next_match_slot = Column(Integer, nullable=True)       # 1 or 2
    loser_next_match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    loser_next_match_slot = Column(Integer, nullable=True)  # 1 or 2
    locked = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
