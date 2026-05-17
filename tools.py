import re
import time
import requests
from typing import Optional

from bs4 import BeautifulSoup
from tavily import TavilyClient

from config import settings


# ─────────────────────────────────────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────────────────────────────────────
tavily = TavilyClient(api_key=settings.TAVILY_API_KEY)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ─────────────────────────────────────────────────────────────────────────────
# TEXT CLEANER
# ─────────────────────────────────────────────────────────────────────────────
def clean_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"[^\x20-\x7E\n]", "", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE — Tavily fetch → BS4 clean → return
# ─────────────────────────────────────────────────────────────────────────────
def scrape_url(url: str, char_limit: int = 6000) -> Optional[str]:
    """
    Pipeline:
    1. Direct requests fetch (always gets fresh/latest content)
    2. Falls back to Tavily if requests fails (for JS-rendered pages)
    3. BS4 cleans noise from HTML
    4. Falls back to raw text if BS4 produces nothing
    """
    raw_content = None
    is_plain_text = False

    # Step 1 — Direct fetch with requests (gets LATEST content)
    print(f"  [scrape] Fetching latest content for: {url}")
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        res.raise_for_status()
        content_type = res.headers.get('content-type', '')
        if 'text/plain' in content_type:
            cleaned = clean_text(res.text[:char_limit])
            if cleaned:
                print(f"  [scrape] Plain text fetched for: {url} ({len(cleaned)} chars)")
                return cleaned
        raw_content = res.text
        print(f"  [requests] Fresh content fetched for: {url} ({len(raw_content)} chars)")
    except Exception as e:
        print(f"  [requests] Failed for {url}: {e}")

    # Step 2 — Fallback to Tavily if requests failed (JS-rendered pages)
    if not raw_content:
        print(f"  [scrape] Falling back to Tavily for: {url}")
        try:
            response = tavily.extract(urls=[url])
            results = response.get("results", [])
            if results and results[0].get("raw_content"):
                raw_content = results[0]["raw_content"]
                print(f"  [tavily] Content fetched for: {url} ({len(raw_content)} chars)")
        except Exception as e:
            print(f"  [tavily] Failed for {url}: {e}")
            return None

    if not raw_content:
        print(f"  [scrape] No content from any source for: {url}")
        return None

    # Step 3 — Check if raw_content is plain text (not HTML)
    is_html = bool(re.search(r"<\s*(html|head|body|div|p|table)\b", raw_content[:500], re.IGNORECASE))

    if not is_html:
        cleaned = clean_text(raw_content)
        if cleaned:
            print(f"  [scrape] Using raw text directly for: {url} ({len(cleaned)} chars)")
            return cleaned[:char_limit]

    # Step 4 — BS4 clean (for HTML content)
    print(f"  [bs4] Cleaning content for: {url}")
    try:
        soup = BeautifulSoup(raw_content, "html.parser")

        for tag in soup(["script", "style", "nav", "footer",
                          "header", "aside", "form", "noscript"]):
            tag.decompose()

        # Try specific content containers first, then fall back broadly
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id="content")
            or soup.find(class_="content")
            or soup.find(id="hnmain")
            or soup.find(class_="storylink")
            or soup.find("table")
            or soup.body
            or soup
        )

        raw = main.get_text(separator=" ", strip=True) if main else ""
        cleaned = clean_text(raw)

        if cleaned:
            print(f"  [bs4] Clean content ready for: {url} ({len(cleaned)} chars)")
            return cleaned[:char_limit]

        # Step 5 — BS4 produced nothing, fall back to raw text
        print(f"  [bs4] No content after cleaning, using raw text fallback for: {url}")
        fallback = re.sub(r"<[^>]+>", " ", raw_content)
        fallback = clean_text(fallback)
        if fallback:
            print(f"  [scrape] Raw text fallback ready for: {url} ({len(fallback)} chars)")
            return fallback[:char_limit]

        print(f"  [scrape] No usable content for: {url}")
        return None

    except Exception as e:
        print(f"  [bs4] Cleaning failed for {url}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# TAVILY SEARCH (optional — for URL discovery)
# ─────────────────────────────────────────────────────────────────────────────
def search_topic(query: str, max_results: int = 5) -> list[dict]:
    try:
        response = tavily.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
        )
        return response.get("results", [])
    except Exception as e:
        print(f"  [tavily search] Failed for query '{query}': {e}")
        return []