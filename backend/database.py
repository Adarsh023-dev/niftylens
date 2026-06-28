# backend/database.py
# Dual-mode storage: SQLite locally, PostgreSQL in production.
# Switches automatically based on whether DATABASE_URL is set in the
# environment — Render sets this when a Postgres instance is linked,
# your local machine never has it, so local behavior is unchanged.

import os
import sqlite3
import json
import time
import logging
from typing import Optional, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IS_POSTGRES = bool(os.environ.get("DATABASE_URL"))

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "niftylens.db")


def get_connection():
    """
    Returns a Postgres connection in production, SQLite locally.
    RealDictCursor makes Postgres rows behave like sqlite3.Row —
    both support row["column_name"] access, so nothing downstream
    needs to know which database it's actually talking to.
    """
    if IS_POSTGRES:
        conn = psycopg2.connect(
            os.environ["DATABASE_URL"],
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        return conn
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


def initialize_database() -> None:
    """
    Create all tables if they don't exist.
    Table syntax here is plain ANSI SQL — REAL/TEXT/INTEGER and
    composite PRIMARY KEY are valid in both SQLite and Postgres,
    so this function needs no dialect branching at all.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                fetched_at  REAL NOT NULL,
                expires_in  INTEGER NOT NULL DEFAULT 900
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_prices (
                symbol      TEXT NOT NULL,
                price       REAL NOT NULL,
                change_pct  REAL NOT NULL,
                volume      INTEGER,
                recorded_at REAL NOT NULL,
                PRIMARY KEY (symbol, recorded_at)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sentiment_scores (
                symbol      TEXT NOT NULL,
                score       REAL NOT NULL,
                headline    TEXT,
                source      TEXT,
                recorded_at REAL NOT NULL,
                PRIMARY KEY (symbol, recorded_at)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_sentiment (
                symbol            TEXT NOT NULL,
                date              TEXT NOT NULL,
                avg_sentiment     REAL NOT NULL,
                price_change_pct  REAL,
                PRIMARY KEY (symbol, date)
            )
        """)

        conn.commit()
        logger.info(
            f"Database initialized "
            f"({'PostgreSQL' if IS_POSTGRES else f'SQLite at {DB_PATH}'})"
        )

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        conn.close()


def cache_set(key: str, data: Any, expires_in: int = 900) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if IS_POSTGRES:
            cursor.execute("""
                INSERT INTO cache (key, value, fetched_at, expires_in)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    fetched_at = EXCLUDED.fetched_at,
                    expires_in = EXCLUDED.expires_in
            """, (key, json.dumps(data), time.time(), expires_in))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO cache (key, value, fetched_at, expires_in)
                VALUES (?, ?, ?, ?)
            """, (key, json.dumps(data), time.time(), expires_in))
        conn.commit()
        logger.debug(f"Cache SET: {key} (expires in {expires_in}s)")
    except Exception as e:
        logger.error(f"Cache set failed for key '{key}': {e}")
        raise
    finally:
        conn.close()


def cache_get(key: str) -> Optional[Any]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        ph = "%s" if IS_POSTGRES else "?"
        cursor.execute(f"""
            SELECT value, fetched_at, expires_in
            FROM cache
            WHERE key = {ph}
        """, (key,))
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"Cache MISS: {key} (not found)")
            return None

        age = time.time() - row["fetched_at"]
        if age > row["expires_in"]:
            logger.debug(f"Cache MISS: {key} (expired, age={age:.0f}s)")
            return None

        logger.debug(f"Cache HIT: {key} (age={age:.0f}s)")
        return json.loads(row["value"])

    except Exception as e:
        logger.error(f"Cache get failed for key '{key}': {e}")
        return None
    finally:
        conn.close()


def cache_invalidate(key: str) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        ph = "%s" if IS_POSTGRES else "?"
        cursor.execute(f"DELETE FROM cache WHERE key = {ph}", (key,))
        conn.commit()
        logger.debug(f"Cache INVALIDATED: {key}")
    except Exception as e:
        logger.error(f"Cache invalidate failed for key '{key}': {e}")
    finally:
        conn.close()


def save_stock_price(symbol: str, price: float,
                     change_pct: float, volume: int) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if IS_POSTGRES:
            cursor.execute("""
                INSERT INTO stock_prices
                (symbol, price, change_pct, volume, recorded_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol, recorded_at) DO UPDATE SET
                    price = EXCLUDED.price,
                    change_pct = EXCLUDED.change_pct,
                    volume = EXCLUDED.volume
            """, (symbol, price, change_pct, volume, time.time()))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO stock_prices
                (symbol, price, change_pct, volume, recorded_at)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, price, change_pct, volume, time.time()))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save price for {symbol}: {e}")
    finally:
        conn.close()


def get_last_known_price(symbol: str) -> Optional[dict]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        ph = "%s" if IS_POSTGRES else "?"
        cursor.execute(f"""
            SELECT symbol, price, change_pct, volume, recorded_at
            FROM stock_prices
            WHERE symbol = {ph}
            ORDER BY recorded_at DESC
            LIMIT 1
        """, (symbol,))
        row = cursor.fetchone()
        if row is None:
            return None

        return {
            "symbol": row["symbol"],
            "price": row["price"],
            "change_pct": row["change_pct"],
            "volume": row["volume"],
            "recorded_at": row["recorded_at"],
            "is_fallback": True
        }
    except Exception as e:
        logger.error(f"Failed to get last price for {symbol}: {e}")
        return None
    finally:
        conn.close()


def save_daily_sentiment(symbol: str, date_str: str,
                         avg_sentiment: float,
                         price_change_pct: Optional[float]) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if IS_POSTGRES:
            cursor.execute("""
                INSERT INTO daily_sentiment
                (symbol, date, avg_sentiment, price_change_pct)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (symbol, date) DO UPDATE SET
                    avg_sentiment = EXCLUDED.avg_sentiment,
                    price_change_pct = EXCLUDED.price_change_pct
            """, (symbol, date_str, avg_sentiment, price_change_pct))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO daily_sentiment
                (symbol, date, avg_sentiment, price_change_pct)
                VALUES (?, ?, ?, ?)
            """, (symbol, date_str, avg_sentiment, price_change_pct))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save daily sentiment for {symbol}: {e}")
    finally:
        conn.close()


def get_sentiment_history(symbol: str, limit: int = 30) -> list:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        ph = "%s" if IS_POSTGRES else "?"
        cursor.execute(f"""
            SELECT date, avg_sentiment, price_change_pct
            FROM daily_sentiment
            WHERE symbol = {ph}
            ORDER BY date DESC
            LIMIT {ph}
        """, (symbol, limit))
        rows = cursor.fetchall()
        return [
            {
                "date": r["date"],
                "avg_sentiment": r["avg_sentiment"],
                "price_change_pct": r["price_change_pct"]
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Failed to get sentiment history for {symbol}: {e}")
        return []
    finally:
        conn.close()