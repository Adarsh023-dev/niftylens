# backend/test_sentiment.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sentiment import scrape_headlines, match_headlines_to_stocks, analyze_stock_sentiment

headlines = scrape_headlines()
print(f"Total headlines: {len(headlines)}\n")

matched = match_headlines_to_stocks(headlines)

# Show only stocks that actually got matched — most won't have news today
matched_stocks = {symbol: hl for symbol, hl in matched.items() if hl}
print(f"Stocks with matching headlines: {len(matched_stocks)}\n")

for symbol, stock_headlines in list(matched_stocks.items())[:5]:
    analysis = analyze_stock_sentiment(symbol, stock_headlines)
    print(f"--- {analysis['symbol']} ---")
    print(f"Headline count: {analysis['headline_count']}")
    print(f"Avg sentiment: {analysis['avg_sentiment']} ({analysis['sentiment_label']})")
    print(f"Extreme headlines: {len(analysis['extreme_headlines'])}")
    print()
    
    # Print the actual headlines for RELIANCE so we can see WHY it scored 0.0
for symbol, stock_headlines in matched.items():
    if symbol == "RELIANCE.NS":
        for h in stock_headlines:
            print(f"RELIANCE headline: {h['headline']}")