"""SQLAlchemy database models for trade history and performance."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Boolean,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = "sqlite:///trading_bot.db"


class Base(DeclarativeBase):
    pass


class TradeRecord(Base):
    """Recorded trade (filled order with outcome)."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    leverage = Column(Integer, default=1)
    strategy = Column(String, nullable=True, index=True)
    is_perp = Column(Boolean, default=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    close_reason = Column(String, nullable=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


class OrderRecord(Base):
    """Recorded order."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, unique=True, nullable=False)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    fill_price = Column(Float, nullable=True)
    status = Column(String, nullable=False)
    strategy = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)


class StrategyRun(Base):
    """Record of a strategy execution cycle."""

    __tablename__ = "strategy_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    signal = Column(String, nullable=False)
    executed_at = Column(DateTime, default=datetime.utcnow)


class PortfolioSnapshot(Base):
    """Periodic portfolio value snapshot."""

    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    total_value = Column(Float, nullable=False)
    spot_value = Column(Float, default=0.0)
    perps_value = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    recorded_at = Column(DateTime, default=datetime.utcnow)


def init_db(db_url: str = DB_PATH) -> sessionmaker:
    """Initialize database and return session factory."""
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
