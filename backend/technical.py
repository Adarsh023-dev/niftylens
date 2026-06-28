# backend/technical.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
import ta
import logging
from typing import Optional
from data_fetcher import fetch_historical_data, NIFTY50_SYMBOLS
from database import cache_get, cache_set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30
MACD_BULLISH   = "Bullish Crossover"
MACD_BEARISH   = "Bearish Crossover"
MACD_NEUTRAL   = "Neutral"


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.momentum.RSIIndicator(
        close=df["Close"], window=period
    ).rsi()


def calculate_macd(df: pd.DataFrame) -> dict:
    macd_indicator = ta.trend.MACD(
        close=df["Close"], window_slow=26, window_fast=12, window_sign=9
    )
    return {
        "macd":      macd_indicator.macd().tolist(),
        "signal":    macd_indicator.macd_signal().tolist(),
        "histogram": macd_indicator.macd_diff().tolist()
    }


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20) -> dict:
    bb = ta.volatility.BollingerBands(
        close=df["Close"], window=period, window_dev=2
    )
    return {
        "upper":  bb.bollinger_hband().tolist(),
        "middle": bb.bollinger_mavg().tolist(),
        "lower":  bb.bollinger_lband().tolist()
    }


def detect_macd_signal(macd_values: list, signal_values: list) -> str:
    valid_pairs = [
        (m, s) for m, s in zip(macd_values, signal_values)
        if m is not None and s is not None
        and not np.isnan(m) and not np.isnan(s)
    ]
    if len(valid_pairs) < 2:
        return MACD_NEUTRAL

    prev_macd, prev_signal = valid_pairs[-2]
    curr_macd, curr_signal = valid_pairs[-1]

    if prev_macd < prev_signal and curr_macd > curr_signal:
        return MACD_BULLISH
    if prev_macd > prev_signal and curr_macd < curr_signal:
        return MACD_BEARISH
    return MACD_NEUTRAL


def get_bb_signal(price: float, upper: float, lower: float) -> str:
    if price >= upper:
        return "At Upper Band"
    if price <= lower:
        return "At Lower Band"
    band_width = upper - lower
    if band_width == 0:
        return "Neutral"
    position_pct = ((price - lower) / band_width) * 100
    if position_pct >= 80:
        return "Near Upper Band"
    if position_pct <= 20:
        return "Near Lower Band"
    return "Middle"


def _build_alerts(rsi_signal: str, macd_signal: str, bb_signal: str) -> list:
    alerts = []
    if rsi_signal == "Overbought":
        alerts.append("⚠️ RSI Overbought (>70)")
    elif rsi_signal == "Oversold":
        alerts.append("🟢 RSI Oversold (<30) — potential bounce")
    if macd_signal == MACD_BULLISH:
        alerts.append("🟢 MACD Bullish Crossover")
    elif macd_signal == MACD_BEARISH:
        alerts.append("🔴 MACD Bearish Crossover")
    if bb_signal in ("At Upper Band", "Near Upper Band"):
        alerts.append("⚠️ Price at Bollinger Upper Band")
    elif bb_signal in ("At Lower Band", "Near Lower Band"):
        alerts.append("🟢 Price at Bollinger Lower Band")
    if not alerts:
        alerts.append("✅ No strong signals")
    return alerts


def analyze_stock(symbol: str) -> Optional[dict]:
    CACHE_KEY    = f"technical_{symbol}"
    CACHE_EXPIRY = 3600

    cached = cache_get(CACHE_KEY)
    if cached is not None:
        return cached

    try:
        df = fetch_historical_data(symbol, period="3mo", interval="1d")

        if df is None:
            logger.warning(f"No data returned for {symbol}")
            return None

        # Cast all numeric columns — JSON cache returns them as objects
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["Close"]).reset_index(drop=True)

        if len(df) < 35:
            logger.warning(f"Insufficient data for {symbol}: {len(df)} rows")
            return None

        rsi_series = calculate_rsi(df)
        macd_data  = calculate_macd(df)
        bb_data    = calculate_bollinger_bands(df)

        current_rsi   = round(float(rsi_series.iloc[-1]), 2)
        current_price = round(float(df["Close"].iloc[-1]), 2)
        current_upper = bb_data["upper"][-1]
        current_lower = bb_data["lower"][-1]

        rsi_signal = (
            "Overbought" if current_rsi >= RSI_OVERBOUGHT else
            "Oversold"   if current_rsi <= RSI_OVERSOLD   else
            "Neutral"
        )
        macd_signal = detect_macd_signal(macd_data["macd"], macd_data["signal"])
        bb_signal   = get_bb_signal(
            current_price,
            current_upper or current_price,
            current_lower or current_price
        )

        def clean(values):
            return [
                round(v, 4) if v is not None and not np.isnan(v) else None
                for v in values
            ]

        dates = df["Date"].tolist() if "Date" in df.columns else []

        result = {
            "symbol":        symbol.replace(".NS", ""),
            "full_symbol":   symbol,
            "current_price": current_price,
            "rsi": {
                "values":  clean(rsi_series.tolist()),
                "current": current_rsi,
                "signal":  rsi_signal
            },
            "macd": {
                "macd":         clean(macd_data["macd"]),
                "signal":       clean(macd_data["signal"]),
                "histogram":    clean(macd_data["histogram"]),
                "signal_label": macd_signal
            },
            "bollinger": {
                "upper":  clean(bb_data["upper"]),
                "middle": clean(bb_data["middle"]),
                "lower":  clean(bb_data["lower"]),
                "signal": bb_signal
            },
            "dates":  dates,
            "alerts": _build_alerts(rsi_signal, macd_signal, bb_signal)
        }

        cache_set(CACHE_KEY, result, CACHE_EXPIRY)
        return result

    except Exception as e:
        logger.error(f"Technical analysis failed for {symbol}: {e}")
        return None


def scan_all_stocks() -> list:
    CACHE_KEY    = "technical_scan_all"
    CACHE_EXPIRY = 3600

    cached = cache_get(CACHE_KEY)
    if cached is not None:
        logger.info("Returning cached technical scan")
        return cached

    results = []
    logger.info("Running full technical scan on all 50 stocks...")

    for symbol in NIFTY50_SYMBOLS:
        analysis = analyze_stock(symbol)
        if analysis is None:
            continue
        results.append({
            "symbol":        analysis["symbol"],
            "current_price": analysis["current_price"],
            "rsi":           analysis["rsi"]["current"],
            "rsi_signal":    analysis["rsi"]["signal"],
            "macd_signal":   analysis["macd"]["signal_label"],
            "bb_signal":     analysis["bollinger"]["signal"],
            "alerts":        analysis["alerts"]
        })

    cache_set(CACHE_KEY, results, CACHE_EXPIRY)
    logger.info(f"Technical scan complete: {len(results)} stocks analyzed")
    return results