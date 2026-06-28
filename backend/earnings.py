# backend/earnings.py
# Quarterly EPS earnings data, surprise % calculation, best/worst rankings
# yfinance earnings data for NSE stocks is inconsistent — every function
# here assumes partial/missing data is NORMAL, not an error

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
import pandas as pd
import logging
from typing import Optional
from data_fetcher import NIFTY50_SYMBOLS
from database import cache_get, cache_set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_surprise_pct(actual: float, estimated: float) -> Optional[float]:
    """
    Calculate earnings surprise as a percentage of estimate.
    Guards against division by a near-zero denominator, which produces
    mathematically valid but practically meaningless percentages.
    """
    if abs(estimated) < 0.20:
        logger.debug(
            f"Estimated EPS too close to zero (est={estimated}) — "
            f"surprise % would be unreliable noise"
        )
        return None

    surprise = ((actual - estimated) / abs(estimated)) * 100
    return round(surprise, 2)



def classify_surprise(surprise_pct: Optional[float]) -> str:
    """
    Label a surprise percentage as Beat / Miss / Inline.

    Thresholds:
        > +2%   → Beat
        < -2%   → Miss
        -2 to +2% → Inline (close enough to estimate to not be notable)
    """
    if surprise_pct is None:
        return "Unknown"
    if surprise_pct > 2:
        return "Beat"
    if surprise_pct < -2:
        return "Miss"
    return "Inline"


def fetch_earnings_for_symbol(symbol: str) -> Optional[dict]:
    """
    Fetch quarterly earnings history for one stock.

    Args:
        symbol: NSE symbol WITH .NS suffix

    Returns:
        Dict with current quarter result + historical surprise trend.
        None if yfinance has no earnings data for this symbol —
        this happens often for NSE stocks, it is NOT an error condition.
    """
    CACHE_KEY = f"earnings_{symbol}"
    CACHE_EXPIRY = 21600  # 6 hours — quarterly data changes rarely

    cached = cache_get(CACHE_KEY)
    if cached is not None:
        return cached

    try:
        ticker = yf.Ticker(symbol)

        # get_earnings_dates returns a DataFrame with columns:
        # EPS Estimate, Reported EPS, Surprise(%)
        # Many NSE symbols return an EMPTY dataframe here — expected, not a bug
        earnings_df = ticker.get_earnings_dates(limit=8)

        if earnings_df is None or earnings_df.empty:
            logger.info(f"No earnings data available for {symbol}")
            return None

        # Drop rows where both EPS columns are missing — can't compute anything
        earnings_df = earnings_df.dropna(
            subset=["EPS Estimate", "Reported EPS"],
            how="all"
        )

        if earnings_df.empty:
            logger.info(f"Earnings data for {symbol} has no usable rows")
            return None

        history = []
        for date, row in earnings_df.iterrows():
            estimated = row.get("EPS Estimate")
            actual    = row.get("Reported EPS")

            # Skip rows where we don't have BOTH values —
            # can't calculate a surprise with only half the data
            if pd.isna(estimated) or pd.isna(actual):
                continue

            estimated = float(estimated)
            actual    = float(actual)

            surprise_pct = calculate_surprise_pct(actual, estimated)

            history.append({
                "date":         str(date.date()),
                "estimated_eps": round(estimated, 2),
                "actual_eps":    round(actual, 2),
                "surprise_pct":  surprise_pct,
                "classification": classify_surprise(surprise_pct)
            })

        if not history:
            logger.info(f"No complete earnings rows for {symbol}")
            return None

        # Sort newest first — get_earnings_dates order isn't guaranteed
        history.sort(key=lambda x: x["date"], reverse=True)

        result = {
            "symbol":      symbol.replace(".NS", ""),
            "full_symbol": symbol,
            "latest":      history[0],
            "history":     history
        }

        cache_set(CACHE_KEY, result, CACHE_EXPIRY)
        return result

    except Exception as e:
        # yfinance throws inconsistent errors per symbol for earnings —
        # one symbol failing must never crash the whole scan
        logger.warning(f"Earnings fetch failed for {symbol}: {e}")
        return None


def scan_all_earnings() -> list[dict]:
    """
    Fetch earnings data for all 50 Nifty stocks.
    Symbols with no earnings data are silently skipped —
    expect roughly 30-60% coverage, NOT all 50.

    Returns:
        List of earnings summaries, one per stock WITH usable data.
    """
    CACHE_KEY = "earnings_scan_all"
    CACHE_EXPIRY = 21600

    cached = cache_get(CACHE_KEY)
    if cached is not None:
        logger.info("Returning cached earnings scan")
        return cached

    results = []
    logger.info("Running earnings scan on all 50 stocks...")

    for symbol in NIFTY50_SYMBOLS:
        data = fetch_earnings_for_symbol(symbol)
        if data is None:
            continue

        results.append({
            "symbol":          data["symbol"],
            "latest_date":     data["latest"]["date"],
            "estimated_eps":   data["latest"]["estimated_eps"],
            "actual_eps":      data["latest"]["actual_eps"],
            "surprise_pct":    data["latest"]["surprise_pct"],
            "classification":  data["latest"]["classification"]
        })

    cache_set(CACHE_KEY, results, CACHE_EXPIRY)
    logger.info(
        f"Earnings scan complete: {len(results)}/{len(NIFTY50_SYMBOLS)} "
        f"stocks had usable data"
    )
    return results


def get_best_worst_performers(scan_results: list[dict], top_n: int = 5) -> dict:
    """
    Rank stocks by surprise % from a completed earnings scan.

    Args:
        scan_results: output of scan_all_earnings()
        top_n: how many best/worst to return

    Returns:
        Dict with "best" and "worst" lists
    """
    # Only rank stocks where surprise_pct is a real number
    rankable = [r for r in scan_results if r["surprise_pct"] is not None]

    if not rankable:
        return {"best": [], "worst": []}

    sorted_results = sorted(
        rankable,
        key=lambda x: x["surprise_pct"],
        reverse=True
    )

    return {
        "best":  sorted_results[:top_n],
        "worst": sorted_results[-top_n:][::-1]
    }