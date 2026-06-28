# backend/inspect_page.py
# Diagnostic script — NOT part of the app, just for inspecting HTML structure
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

url = "https://www.moneycontrol.com/news/business/markets/"
response = requests.get(url, headers=HEADERS, timeout=10)
soup = BeautifulSoup(response.text, "html.parser")

# Print the first 15 <a> tags WITH their class attribute and parent tag
# This shows us the real structure instead of guessing
links = soup.find_all("a")
print(f"Total <a> tags found: {len(links)}\n")

count = 0
for link in links:
    text = link.get_text(strip=True)
    if 20 <= len(text) <= 200:
        parent = link.parent.name if link.parent else "none"
        parent_class = link.parent.get("class") if link.parent else None
        link_class = link.get("class")
        print(f"TEXT: {text[:80]}")
        print(f"  link class: {link_class} | parent: <{parent} class={parent_class}>")
        print()
        count += 1
        if count >= 15:
            break