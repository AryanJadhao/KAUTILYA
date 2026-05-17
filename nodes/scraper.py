from tools import scrape_url
from schemas import AgentState


def scrape_websites(state: AgentState) -> AgentState:
    """Scrape all URLs and store clean text in state."""
    print("--- NODE: scrape_websites ---")
    scraped_data = {}

    for url in state["urls"]:
        content = scrape_url(url)
        if content:
            scraped_data[url] = content
        else:
            print(f"  [scraper] Skipping {url} — no content returned")

    return {"current_content": scraped_data}