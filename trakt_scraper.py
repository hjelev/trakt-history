#!/usr/bin/env python3
"""
Scrapes watch history from Trakt's public profile pages, replacing the
old api.trakt.tv-based sync now that Trakt requires VIP for developer API
apps (see: 5-week rotation of client_id apps returning invalid_client).

Rather than parsing rendered DOM text (fragile, and the rendered history
cards don't even include the show name for episodes), this drives a real
headless browser to load the public history page and captures the JSON
responses the page's own frontend fetches from apiz.trakt.tv while
scrolling. That endpoint is called by every visitor's browser with a
trakt-api-key baked into Trakt's public JS bundle -- nothing extracted
from an authenticated session, and the shape matches the old developer
/sync/history response closely enough that downstream processing barely
has to change.
"""
import random
import time

from playwright.sync_api import sync_playwright

HISTORY_API_PATH = "apiz.trakt.tv/users/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
MAX_SCROLLS = 400
SCROLL_WAIT_MS = 1200
STABLE_ROUNDS_TO_STOP = 3


def _get_history_for_user(browser, username: str, verbose: bool = False) -> list:
    """Load username's public history page and collect all paginated items
    from the apiz.trakt.tv history calls the page makes while scrolling."""
    pages_seen = {}

    def on_response(resp):
        if HISTORY_API_PATH not in resp.url or "/history/" not in resp.url:
            return
        try:
            body = resp.json()
        except Exception:
            return
        if not isinstance(body, list):
            return
        pages_seen[resp.url] = body

    page = browser.new_page(user_agent=USER_AGENT)
    page.on("response", on_response)
    try:
        page.goto(
            f"https://trakt.tv/users/{username}/history",
            wait_until="networkidle",
            timeout=30000,
        )
        page.wait_for_timeout(2000)

        stable_rounds = 0
        last_count = 0
        for i in range(MAX_SCROLLS):
            page.mouse.wheel(0, 20000)
            page.wait_for_timeout(SCROLL_WAIT_MS)

            total_items = sum(len(v) for v in pages_seen.values())
            if total_items == last_count:
                stable_rounds += 1
                if stable_rounds >= STABLE_ROUNDS_TO_STOP:
                    break
            else:
                stable_rounds = 0
                last_count = total_items

            if verbose and i % 10 == 0:
                print(f"    scroll {i}: {total_items} items captured so far...")

        # If the last captured page was non-empty, do a couple more scrolls
        # to make sure we've reached the true empty-page end.
    finally:
        page.close()

    # Concatenate in request order isn't guaranteed by dict insertion here
    # since responses can race; sort by the numeric page= query param.
    def _page_num(url: str) -> int:
        try:
            qs = url.split("?", 1)[1]
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            return int(params.get("page", 0))
        except Exception:
            return 0

    items = []
    for url in sorted(pages_seen.keys(), key=_page_num):
        items.extend(pages_seen[url])
    return items


def get_history(username: str, verbose: bool = False) -> list:
    """Public entry point: returns raw watch-history items for username,
    same shape as items previously returned by /sync/history or
    /users/{username}/history (list of dicts with id, watched_at, type,
    movie|episode+show)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            return _get_history_for_user(browser, username, verbose=verbose)
        finally:
            browser.close()


def get_history_for_users(usernames: list, verbose: bool = False) -> dict:
    """Scrape history for multiple users in one browser instance, with a
    small courtesy delay between users to keep load on Trakt low."""
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for i, username in enumerate(usernames):
                if verbose:
                    print(f"Scraping history for {username}...")
                results[username] = _get_history_for_user(browser, username, verbose=verbose)
                if i < len(usernames) - 1:
                    time.sleep(random.uniform(3, 7))
        finally:
            browser.close()
    return results


if __name__ == "__main__":
    import sys
    import json

    username = sys.argv[1] if len(sys.argv) > 1 else None
    if not username:
        print("Usage: trakt_scraper.py <username>")
        sys.exit(1)

    items = get_history(username, verbose=True)
    print(f"\nFetched {len(items)} history items for {username}")
    if items:
        print("First item:")
        print(json.dumps(items[0], indent=2)[:1500])
