# backend/main.py
# FastAPI application — entry point for the entire NiftyLens backend
# Run with: uvicorn backend.main:app --reload
# backend/main.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from sentiment import scan_all_sentiment, get_sentiment_correlation
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import logging

from database import initialize_database
from data_fetcher import (
    fetch_nifty50_prices,
    fetch_historical_data,
    get_gainers_losers,
    get_sector_performance,
    NIFTY50_SYMBOLS
)
from technical import analyze_stock, scan_all_stocks
from earnings import scan_all_earnings, fetch_earnings_for_symbol, get_best_worst_performers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- App initialization ---
app = FastAPI(
    title="NiftyLens API",
    description="Indian Stock Market Intelligence Platform",
    version="1.0.0"
)

# --- CORS Middleware ---
# Without this, your browser will block frontend → backend requests
# This is a security feature browsers enforce — we explicitly allow our frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten this to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Serve frontend static files ---
# This lets FastAPI serve your HTML/CSS/JS directly
# So you only need ONE server running, not two
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend"
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# --- Startup event ---
@app.on_event("startup")
async def startup_event():
    """
    Runs once when the server starts.
    Initialize database tables before any request is served.
    """
    logger.info("NiftyLens starting up...")
    initialize_database()
    logger.info("Database ready")


# --- Health check ---
@app.get("/api/health")
async def health_check():
    """
    Lightweight endpoint to confirm the server is alive.
    Render uses this to detect if the app is running.
    """
    return {"status": "ok", "message": "NiftyLens is running"}


# --- Module 1: Market Pulse endpoints ---

@app.get("/api/prices")
async def get_prices():
    """
    Returns current prices for all 50 Nifty stocks.
    Cached for 15 minutes — safe to call on every page load.
    """
    try:
        prices = fetch_nifty50_prices()
        return {
            "status": "ok",
            "count": len(prices),
            "data": prices
        }
    except Exception as e:
        logger.error(f"/api/prices failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch prices. Market may be closed or data source unavailable."
        )


@app.get("/api/gainers-losers")
async def get_gainers_losers_endpoint():
    """
    Returns top 5 gainers and top 5 losers for the day.
    Derived from the same cached price data — no extra yfinance call.
    """
    try:
        prices = fetch_nifty50_prices()
        result = get_gainers_losers(prices)
        return {"status": "ok", "data": result}
    except Exception as e:
        logger.error(f"/api/gainers-losers failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/sector-performance")
async def get_sector_performance_endpoint():
    """
    Returns average % change per sector.
    Powers the heatmap on the dashboard.
    """
    try:
        prices = fetch_nifty50_prices()
        result = get_sector_performance(prices)
        return {"status": "ok", "data": result}
    except Exception as e:
        logger.error(f"/api/sector-performance failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/historical/{symbol}")
async def get_historical(symbol: str, period: str = "3mo"):
    """
    Returns historical OHLCV data for a single stock.
    Used by Phase 2 technical analysis charts.

    Args:
        symbol: Stock symbol WITHOUT .NS suffix (e.g. "RELIANCE")
        period: "1mo", "3mo", "6mo", "1y"
    """
    full_symbol = f"{symbol.upper()}.NS"

    if full_symbol not in NIFTY50_SYMBOLS:
        raise HTTPException(
            status_code=404,
            detail=f"{symbol} is not a Nifty50 constituent"
        )

    try:
        df = fetch_historical_data(full_symbol, period=period)
        if df is None:
            raise HTTPException(
                status_code=503,
                detail=f"Could not fetch historical data for {symbol}"
            )
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "period": period,
            "data": df.to_dict(orient="records")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/historical/{symbol} failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))

# ── Module 2: Technical Scanner endpoints ──

@app.get("/api/technical/scan")
async def get_technical_scan():
    """
    Returns RSI, MACD, BB signals for all 50 stocks.
    First call takes 2-3 minutes. Cached for 1 hour after that.
    """
    try:
        results = scan_all_stocks()
        return {"status": "ok", "count": len(results), "data": results}
    except Exception as e:
        logger.error(f"/api/technical/scan failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/technical/{symbol}")
async def get_technical_analysis(symbol: str):
    """
    Returns full technical analysis + chart data for one stock.
    Args:
        symbol: without .NS suffix (e.g. "RELIANCE")
    """
    full_symbol = f"{symbol.upper()}.NS"

    if full_symbol not in NIFTY50_SYMBOLS:
        raise HTTPException(
            status_code=404,
            detail=f"{symbol} is not a Nifty50 constituent"
        )

    try:
        result = analyze_stock(full_symbol)
        if result is None:
            raise HTTPException(
                status_code=503,
                detail=f"Could not analyze {symbol}"
            )
        return {"status": "ok", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/technical/{symbol} failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    
# ── Module 3: Earnings Radar endpoints ──

@app.get("/api/earnings/scan")
async def get_earnings_scan():
    """
    Returns latest quarterly earnings surprise data for all Nifty50 stocks.
    Expect partial coverage — yfinance does not have earnings data
    for every NSE symbol. This is normal, not a bug.
    """
    try:
        results = scan_all_earnings()
        best_worst = get_best_worst_performers(results)
        return {
            "status": "ok",
            "count": len(results),
            "data": results,
            "best_worst": best_worst
        }
    except Exception as e:
        logger.error(f"/api/earnings/scan failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/earnings/{symbol}")
async def get_earnings_for_stock(symbol: str):
    """
    Returns full earnings history + surprise trend for one stock.
    Args:
        symbol: without .NS suffix (e.g. "RELIANCE")
    """
    full_symbol = f"{symbol.upper()}.NS"

    if full_symbol not in NIFTY50_SYMBOLS:
        raise HTTPException(
            status_code=404,
            detail=f"{symbol} is not a Nifty50 constituent"
        )

    try:
        result = fetch_earnings_for_symbol(full_symbol)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No earnings data available for {symbol}"
            )
        return {"status": "ok", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/earnings/{symbol} failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    
    # ── Module 4: Sentiment Engine endpoints ──

@app.get("/api/sentiment/scan")
async def get_sentiment_scan():
    """
    Returns sentiment analysis for all Nifty50 stocks with matching news.
    Coverage is partial — most stocks won't have news on any given day.
    """
    try:
        results = scan_all_sentiment()
        return {"status": "ok", "count": len(results), "data": results}
    except Exception as e:
        logger.error(f"/api/sentiment/scan failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/sentiment/correlation/{symbol}")
async def get_correlation(symbol: str):
    """
    Returns sentiment-vs-price correlation for one stock.
    Requires 5+ days of accumulated history — returns
    'insufficient_data' status otherwise, not an error.
    """
    full_symbol = f"{symbol.upper()}.NS"
    if full_symbol not in NIFTY50_SYMBOLS:
        raise HTTPException(
            status_code=404,
            detail=f"{symbol} is not a Nifty50 constituent"
        )

    try:
        result = get_sentiment_correlation(symbol)
        return {"status": "ok", "data": result}
    except Exception as e:
        logger.error(f"/api/sentiment/correlation/{symbol} failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))
# --- Root route ---
@app.get("/")
async def serve_frontend():
    """Serve the main dashboard HTML file."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "NiftyLens API running. Frontend not yet built."}