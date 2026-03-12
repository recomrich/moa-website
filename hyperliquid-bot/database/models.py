"""
Modèles SQLAlchemy — définition des tables de la base de données.

Persiste l'historique des trades, les ordres et les runs de stratégies
pour l'analyse de performance et le backtesting.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

DATABASE_URL = "sqlite:///data/hyperbot.db"


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy."""
    pass


class Trade(Base):
    """Historique des trades exécutés."""

    __tablename__ = "trades"

    id = Column(String, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)           # "long" ou "short"
    market_type = Column(String, default="perps")   # "spot" ou "perps"
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    size = Column(Float, nullable=False)
    leverage = Column(Float, default=1.0)
    pnl = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    strategy_name = Column(String, nullable=True, index=True)
    close_reason = Column(String, nullable=True)     # "sl", "tp", "manual", "strategy"
    is_paper = Column(Boolean, default=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Trade {self.symbol} {self.side} @ {self.entry_price} "
            f"PnL: {self.pnl:.2f}>"
        )


class Order(Base):
    """Historique de tous les ordres passés."""

    __tablename__ = "orders"

    id = Column(String, primary_key=True)
    exchange_order_id = Column(Integer, nullable=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)            # "buy" ou "sell"
    order_type = Column(String, nullable=False)      # "market", "limit"
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    filled_size = Column(Float, default=0.0)
    avg_fill_price = Column(Float, default=0.0)
    status = Column(String, nullable=False)          # "filled", "cancelled", etc.
    strategy_name = Column(String, nullable=True)
    is_paper = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Order {self.symbol} {self.side} {self.size} @ {self.price}>"


class StrategyRun(Base):
    """Log des exécutions et signaux des stratégies."""

    __tablename__ = "strategy_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    signal = Column(String, nullable=False)          # "buy", "sell", "hold"
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    confidence = Column(Float, default=1.0)
    reason = Column(String, nullable=True)
    acted_upon = Column(Boolean, default=False)      # Signal tradé ou non
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return (
            f"<StrategyRun {self.strategy_name} {self.symbol} {self.signal} "
            f"@ {self.created_at}>"
        )


class EquitySnapshot(Base):
    """Instantanés périodiques de l'équity du portefeuille."""

    __tablename__ = "equity_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    equity = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl_today = Column(Float, default=0.0)
    open_positions = Column(Integer, default=0)
    is_paper = Column(Boolean, default=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<EquitySnapshot {self.equity:.2f} @ {self.recorded_at}>"


def create_all_tables(db_url: str = DATABASE_URL) -> None:
    """
    Crée toutes les tables si elles n'existent pas.

    Args:
        db_url: URL de la base de données SQLite.
    """
    import os
    os.makedirs("data", exist_ok=True)
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)


def get_engine(db_url: str = DATABASE_URL):
    """Retourne l'engine SQLAlchemy configuré."""
    import os
    os.makedirs("data", exist_ok=True)
    return create_engine(db_url, echo=False)
