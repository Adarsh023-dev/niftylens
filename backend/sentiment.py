# backend/sentiment.py
# Scrapes financial news headlines, scores sentiment with VADER,
# correlates sentiment with price movement.
#
# Design constraint: scrape a SMALL number of general news pages,
# then filter for stock mentions — never one request per stock.
# Hitting a news site 50x rapidly risks getting our IP blocked.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import logging
import time
from typing import Optional
from data_fetcher import NIFTY50_SYMBOLS, fetch_nifty50_prices
from database import cache_get, cache_set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

analyzer = SentimentIntensityAnalyzer()

# Stock name → symbol mapping for headline matching
# Headlines say "Reliance" not "RELIANCE.NS" — we need to match company
# names, not ticker symbols, when scanning headline text
STOCK_NAME_MAP = {
    "RELIANCE.NS":   ["Reliance", "RIL"],
    "TCS.NS":        ["TCS", "Tata Consultancy"],
    "HDFCBANK.NS":   ["HDFC Bank"],
    "BHARTIARTL.NS": ["Bharti Airtel", "Airtel"],
    "ICICIBANK.NS":  ["ICICI Bank"],
    "INFOSYS.NS":    ["Infosys"],
    "SBIN.NS":       ["SBI", "State Bank"],
    "HINDUNILVR.NS": ["Hindustan Unilever", "HUL"],
    "ITC.NS":        ["ITC"],
    "LT.NS":         ["Larsen", "L&T"],
    "KOTAKBANK.NS":  ["Kotak"],
    "AXISBANK.NS":   ["Axis Bank"],
    "ASIANPAINT.NS": ["Asian Paints"],
    "MARUTI.NS":     ["Maruti"],
    "SUNPHARMA.NS":  ["Sun Pharma"],
    "TITAN.NS":      ["Titan"],
    "ULTRACEMCO.NS": ["UltraTech"],
    "WIPRO.NS":      ["Wipro"],
    "ONGC.NS":       ["ONGC"],
    "NTPC.NS":       ["NTPC"],
    "POWERGRID.NS":  ["Power Grid"],
    "TECHM.NS":      ["Tech Mahindra"],
    "BAJFINANCE.NS": ["Bajaj Finance"],
    "HCLTECH.NS":    ["HCL Tech"],
    "COALINDIA.NS":  ["Coal India"],
    "TATAMOTORS.NS": ["Tata Motors"],
    "DRREDDY.NS":    ["Dr Reddy"],
    "BAJAJFINSV.NS": ["Bajaj Finserv"],
    "ADANIENT.NS":   ["Adani Enterprises"],
    "JSWSTEEL.NS":   ["JSW Steel"],
    "TATASTEEL.NS":  ["Tata Steel"],
    "NESTLEIND.NS":  ["Nestle"],
    "M&M.NS":        ["Mahindra"],
    "GRASIM.NS":     ["Grasim"],
    "DIVISLAB.NS":   ["Divi's Lab"],
    "CIPLA.NS":      ["Cipla"],
    "HEROMOTOCO.NS": ["Hero MotoCorp"],
    "ADANIPORTS.NS": ["Adani Ports"],
    "INDUSINDBK.NS": ["IndusInd Bank"],
    "EICHERMOT.NS":  ["Eicher Motors"],
    "BRITANNIA.NS":  ["Britannia"],
    "APOLLOHOSP.NS": ["Apollo Hospitals"],
    "TATACONSUM.NS": ["Tata Consumer"],
    "HINDALCO.NS":   ["Hindalco"],
    "BPCL.NS":       ["BPCL", "Bharat Petroleum"],
    "SBILIFE.NS":    ["SBI Life"],
    "HDFCLIFE.NS":   ["HDFC Life"],
    "BAJAJ-AUTO.NS": ["Bajaj Auto"],
    "SHRIRAMFIN.NS": ["Shriram Finance"],
    "BEL.NS":        ["Bharat Electronics"],
}

# Headers to look like a real browser, not a bot script
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# RSS feeds — structured XML built for syndication, not HTML pages to scrape.
# This avoids the exact problem we just hit: JS-rendered content and
# nav/widget pollution that plain HTML scraping can't reliably filter out.
NEWS_SOURCES = [
    {
        "name": "MoneyControl",
        "url": "http://www.moneycontrol.com/rss/latestnews.xml",
    },
    {
        "name": "Economic Times",
        "url": "https://economictimes.indiatimes.com/rssfeedsdefault.cms",
    },
]


import feedparser

def scrape_headlines() -> list[dict]:
    """
    Fetch headlines from RSS feeds — structured XML, not HTML scraping.
    RSS titles are guaranteed clean (no nav menus, no JS-only content,
    no ticker widgets) because RSS is built for syndication.
    """
    all_headlines = []

    for source in NEWS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])

            if feed.bozo:
                # bozo flag means the XML was malformed or unreachable —
                # log it but don't crash, same graceful degradation pattern
                logger.warning(
                    f"Feed parsing issue for {source['name']}: {feed.bozo_exception}"
                )

            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if 15 <= len(title) <= 200:
                    all_headlines.append({
                        "headline": title,
                        "source": source["name"]
                    })

        except Exception as e:
            # One feed failing must not kill the whole scrape
            logger.warning(f"Failed to fetch RSS from {source['name']}: {e}")
            continue

    # Deduplicate — same story sometimes appears more than once
    seen = set()
    unique_headlines = []
    for h in all_headlines:
        if h["headline"] not in seen:
            seen.add(h["headline"])
            unique_headlines.append(h)

    logger.info(f"Fetched {len(unique_headlines)} unique headlines from RSS")
    return unique_headlines

import re

def match_headlines_to_stocks(headlines: list[dict]) -> dict:
    """
    Filter scraped headlines for stock name mentions.

    Uses word-boundary matching (\\b) instead of plain substring matching.
    Plain substring matching causes false positives — e.g. "RIL" (short
    for Reliance) would incorrectly match inside "Drilling" because
    "ril" appears as a substring of that unrelated word.

    Args:
        headlines: output of scrape_headlines()

    Returns:
        Dict mapping symbol -> list of matching headline dicts
    """
    matches: dict[str, list] = {symbol: [] for symbol in NIFTY50_SYMBOLS}

    for headline_data in headlines:
        text = headline_data["headline"]

        for symbol, names in STOCK_NAME_MAP.items():
            matched_this_symbol = False
            for name in names:
                # \b = word boundary — ensures "RIL" matches as a whole
                # word, not as a substring inside "Drilling"
                pattern = r'\b' + re.escape(name) + r'\b'
                if re.search(pattern, text, re.IGNORECASE):
                    matches[symbol].append(headline_data)
                    matched_this_symbol = True
                    break
            if matched_this_symbol:
                continue

    return matches

def score_headline(text: str) -> float:
    """
    Score a single headline using VADER.
    Returns compound score: -1 (very negative) to +1 (very positive).
    """
    scores = analyzer.polarity_scores(text)
    return round(scores["compound"], 3)


def analyze_stock_sentiment(symbol: str, headlines: list[dict]) -> Optional[dict]:
    """
    Calculate sentiment summary for one stock from its matched headlines.

    Returns BOTH average sentiment AND flagged extreme headlines —
    this is the dual-metric design we reasoned through earlier:
    average alone hides outliers, extreme alone ignores the majority.

    Args:
        symbol: NSE symbol with .NS suffix
        headlines: list of headline dicts matched to this stock

    Returns:
        None if zero headlines found — that's a normal, expected outcome
        for many stocks on any given day, not an error.
    """
    if not headlines:
        return None

    scored = []
    for h in headlines:
        score = score_headline(h["headline"])
        scored.append({
            "headline": h["headline"],
            "source": h["source"],
            "score": score
        })

    avg_score = round(sum(s["score"] for s in scored) / len(scored), 3)

    # Flag headlines that cross a strong threshold — these are the
    # "scandal" or "major news" signals that averaging would hide
    EXTREME_THRESHOLD = 0.5
    extreme_headlines = [
        s for s in scored
        if abs(s["score"]) >= EXTREME_THRESHOLD
    ]

    # Overall classification based on average
    if avg_score >= 0.2:
        sentiment_label = "Positive"
    elif avg_score <= -0.2:
        sentiment_label = "Negative"
    else:
        sentiment_label = "Neutral"

    return {
        "symbol": symbol.replace(".NS", ""),
        "full_symbol": symbol,
        "headline_count": len(scored),
        "avg_sentiment": avg_score,
        "sentiment_label": sentiment_label,
        "extreme_headlines": extreme_headlines,
        "all_headlines": scored
    }


from datetime import date as date_module
from database import cache_get, cache_set, save_daily_sentiment, get_sentiment_history


def scan_all_sentiment() -> list[dict]:
    """
    Scrape news once, match to all 50 stocks, score sentiment for each.
    Also saves today's snapshot to daily_sentiment for future correlation —
    one row per symbol per calendar day (overwritten if scan re-runs today).

    Coverage will be PARTIAL — most stocks won't have news on any given
    day. This is expected, not an error — same pattern as earnings.py.
    """
    CACHE_KEY = "sentiment_scan_all"
    CACHE_EXPIRY = 1800  # 30 minutes — news changes faster than earnings

    cached = cache_get(CACHE_KEY)
    if cached is not None:
        logger.info("Returning cached sentiment scan")
        return cached

    logger.info("Scraping news for sentiment analysis...")
    headlines = scrape_headlines()

    if not headlines:
        logger.warning("No headlines scraped — news sources may be unreachable")
        return []

    matched = match_headlines_to_stocks(headlines)

    # Get today's prices once — needed to pair with sentiment for the
    # daily snapshot. Reuses the existing cached price fetch, no extra
    # yfinance calls.
    today_prices = {p["full_symbol"]: p["change_pct"] for p in fetch_nifty50_prices()}
    today_str = date_module.today().isoformat()

    results = []
    for symbol in NIFTY50_SYMBOLS:
        stock_headlines = matched.get(symbol, [])
        analysis = analyze_stock_sentiment(symbol, stock_headlines)

        if analysis is not None:
            results.append(analysis)

            # Save daily snapshot — this is what accumulates over time
            # to eventually make correlation calculation possible
            price_change = today_prices.get(symbol)
            save_daily_sentiment(
                symbol=symbol,
                date_str=today_str,
                avg_sentiment=analysis["avg_sentiment"],
                price_change_pct=price_change
            )

    cache_set(CACHE_KEY, results, CACHE_EXPIRY)
    logger.info(
        f"Sentiment scan complete: {len(results)}/{len(NIFTY50_SYMBOLS)} "
        f"stocks had matching news today"
    )
    return results

def get_sentiment_correlation(symbol: str) -> dict:
    """
    Calculate correlation between historical sentiment and price movement
    for one stock. Requires minimum 5 days of history to be meaningful —
    returns an explicit "insufficient data" state otherwise, same pattern
    as our other None-returning guards.
    """
    full_symbol = f"{symbol.upper()}.NS" if not symbol.endswith(".NS") else symbol
    history = get_sentiment_history(full_symbol, limit=30)

    MIN_DAYS_REQUIRED = 5

    # Filter out days where price data was missing (market closed, etc.)
    usable_history = [
        h for h in history
        if h["price_change_pct"] is not None
    ]

    if len(usable_history) < MIN_DAYS_REQUIRED:
        return {
            "symbol": symbol.upper(),
            "status": "insufficient_data",
            "days_available": len(usable_history),
            "days_required": MIN_DAYS_REQUIRED,
            "correlation": None,
            "history": history
        }

    # Simple Pearson correlation calculation, no extra library needed
    sentiments = [h["avg_sentiment"] for h in usable_history]
    price_changes = [h["price_change_pct"] for h in usable_history]

    n = len(sentiments)
    mean_sent = sum(sentiments) / n
    mean_price = sum(price_changes) / n

    numerator = sum(
        (sentiments[i] - mean_sent) * (price_changes[i] - mean_price)
        for i in range(n)
    )
    denom_sent = sum((s - mean_sent) ** 2 for s in sentiments) ** 0.5
    denom_price = sum((p - mean_price) ** 2 for p in price_changes) ** 0.5

    if denom_sent == 0 or denom_price == 0:
        # No variation in sentiment or price across the period —
        # correlation is mathematically undefined here, same zero-
        # denominator pattern as earnings surprise %
        correlation = None
    else:
        correlation = round(numerator / (denom_sent * denom_price), 3)

    return {
        "symbol": symbol.upper(),
        "status": "ok",
        "days_available": n,
        "days_required": MIN_DAYS_REQUIRED,
        "correlation": correlation,
        "history": history
    }