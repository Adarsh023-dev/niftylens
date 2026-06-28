# backend/data_fetcher.py
import yfinance as yf
import pandas as pd
import logging
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import cache_get, cache_set, save_stock_price, get_last_known_price

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NIFTY50_SYMBOLS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS",
    "INFOSYS.NS", "SBIN.NS", "HINDUNILVR.NS", "ITC.NS", "LT.NS",
    "KOTAKBANK.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS", "ONGC.NS", "NTPC.NS",
    "POWERGRID.NS", "TECHM.NS", "BAJFINANCE.NS", "HCLTECH.NS", "COALINDIA.NS",
    "TATAMOTORS.NS", "DRREDDY.NS", "BAJAJFINSV.NS", "ADANIENT.NS", "JSWSTEEL.NS",
    "TATASTEEL.NS", "NESTLEIND.NS", "M&M.NS", "GRASIM.NS", "DIVISLAB.NS",
    "CIPLA.NS", "HEROMOTOCO.NS", "ADANIPORTS.NS", "INDUSINDBK.NS", "EICHERMOT.NS",
    "BRITANNIA.NS", "APOLLOHOSP.NS", "TATACONSUM.NS", "HINDALCO.NS", "BPCL.NS",
    "SBILIFE.NS", "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "SHRIRAMFIN.NS", "BEL.NS"
]

SECTOR_MAP = {
    "RELIANCE.NS": "Energy", "ONGC.NS": "Energy", "BPCL.NS": "Energy",
    "COALINDIA.NS": "Energy", "NTPC.NS": "Energy", "POWERGRID.NS": "Energy",
    "TCS.NS": "IT", "INFOSYS.NS": "IT", "WIPRO.NS": "IT",
    "HCLTECH.NS": "IT", "TECHM.NS": "IT",
    "HDFCBANK.NS": "Banking", "ICICIBANK.NS": "Banking", "SBIN.NS": "Banking",
    "KOTAKBANK.NS": "Banking", "AXISBANK.NS": "Banking", "INDUSINDBK.NS": "Banking",
    "BAJFINANCE.NS": "Finance", "BAJAJFINSV.NS": "Finance", "SBILIFE.NS": "Finance",
    "HDFCLIFE.NS": "Finance", "SHRIRAMFIN.NS": "Finance",
    "HINDUNILVR.NS": "FMCG", "ITC.NS": "FMCG", "NESTLEIND.NS": "FMCG",
    "BRITANNIA.NS": "FMCG", "TATACONSUM.NS": "FMCG",
    "SUNPHARMA.NS": "Pharma", "DRREDDY.NS": "Pharma", "CIPLA.NS": "Pharma",
    "DIVISLAB.NS": "Pharma", "APOLLOHOSP.NS": "Pharma",
    "MARUTI.NS": "Auto", "TATAMOTORS.NS": "Auto", "M&M.NS": "Auto",
    "HEROMOTOCO.NS": "Auto", "BAJAJ-AUTO.NS": "Auto", "EICHERMOT.NS": "Auto",
    "LT.NS": "Infrastructure", "ADANIPORTS.NS": "Infrastructure",
    "ADANIENT.NS": "Infrastructure", "BEL.NS": "Infrastructure",
    "ASIANPAINT.NS": "Consumer", "TITAN.NS": "Consumer",
    "TATASTEEL.NS": "Metals", "JSWSTEEL.NS": "Metals", "HINDALCO.NS": "Metals",
    "ULTRACEMCO.NS": "Cement", "GRASIM.NS": "Cement",
    "BHARTIARTL.NS": "Telecom",
}


def fetch_nifty50_prices() -> list[dict]:
    """
    Fetch current day prices for all Nifty50 stocks.
    Uses history() — works even when market is closed.
    """
    CACHE_KEY = "nifty50_prices"
    CACHE_EXPIRY = 900

    cached = cache_get(CACHE_KEY)
    if cached is not None:
        logger.info("Returning cached Nifty50 prices")
        return cached

    logger.info("Cache miss — fetching from yfinance")
    results = []

    try:
        for symbol in NIFTY50_SYMBOLS:
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="5d")

                if df.empty or len(df) < 2:
                    raise ValueError(f"Insufficient history data for {symbol}")

                latest = df.iloc[-1]
                previous = df.iloc[-2]

                price = round(float(latest["Close"]), 2)
                prev_close = round(float(previous["Close"]), 2)
                change = round(price - prev_close, 2)
                change_pct = round((change / prev_close) * 100, 2)
                volume = int(latest["Volume"])

                stock_data = {
                    "symbol": symbol.replace(".NS", ""),
                    "full_symbol": symbol,
                    "price": price,
                    "prev_close": prev_close,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": volume,
                    "sector": SECTOR_MAP.get(symbol, "Other")
                }

                results.append(stock_data)
                save_stock_price(symbol, price, change_pct, volume)

            except Exception as e:
                logger.warning(f"Failed to fetch {symbol}: {e}")
                fallback = get_last_known_price(symbol)
                if fallback:
                    fallback["symbol"] = symbol.replace(".NS", "")
                    fallback["full_symbol"] = symbol
                    fallback["sector"] = SECTOR_MAP.get(symbol, "Other")
                    results.append(fallback)

        if not results:
            raise ValueError("Zero stocks fetched — yfinance may be down")

        cache_set(CACHE_KEY, results, CACHE_EXPIRY)
        logger.info(f"Fetched {len(results)} stocks, cached for {CACHE_EXPIRY}s")
        return results

    except Exception as e:
        logger.error(f"Fatal error in fetch_nifty50_prices: {e}")
        raise


def fetch_historical_data(symbol: str,
                          period: str = "3mo",
                          interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV historical data for a single symbol.
    Used by technical.py for RSI, MACD, Bollinger Band calculations.
    """
    CACHE_KEY = f"historical_{symbol}_{period}_{interval}"
    CACHE_EXPIRY = 3600

    cached = cache_get(CACHE_KEY)
    if cached is not None:
        return pd.DataFrame(cached)

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)

        if df.empty:
            logger.warning(f"Empty historical data for {symbol}")
            return None

        df = df.reset_index()
        df["Date"] = df["Date"].astype(str)
        cache_set(CACHE_KEY, df.to_dict(orient="records"), CACHE_EXPIRY)
        return df

    except Exception as e:
        logger.error(f"Failed to fetch historical data for {symbol}: {e}")
        return None


def get_gainers_losers(prices: list[dict]) -> dict:
    """Top 5 gainers and losers from price list."""
    if not prices:
        return {"gainers": [], "losers": []}

    live_prices = [p for p in prices if not p.get("is_fallback", False)]
    sorted_by_change = sorted(live_prices,
                              key=lambda x: x["change_pct"],
                              reverse=True)
    return {
        "gainers": sorted_by_change[:5],
        "losers": sorted_by_change[-5:][::-1]
    }


def get_sector_performance(prices: list[dict]) -> list[dict]:
    """Average % change per sector for the heatmap."""
    if not prices:
        return []

    sector_data: dict[str, list[float]] = {}

    for stock in prices:
        sector = stock.get("sector", "Other")
        change_pct = stock.get("change_pct", 0.0)
        if sector not in sector_data:
            sector_data[sector] = []
        sector_data[sector].append(change_pct)

    result = []
    for sector, changes in sector_data.items():
        result.append({
            "sector": sector,
            "avg_change_pct": round(sum(changes) / len(changes), 2),
            "stock_count": len(changes)
        })

    return sorted(result, key=lambda x: x["avg_change_pct"], reverse=True)