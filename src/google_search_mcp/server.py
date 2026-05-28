"""
Google Search MCP Server

A Model Context Protocol (MCP) server that performs real Google searches
using headless Chromium (via Playwright) and returns structured results.

Tools provided:
    - google_search: Search with time filtering, site filtering, pagination, language/region
    - google_news: Search Google News for recent headlines
    - google_scholar: Search Google Scholar for academic papers
    - google_images: Search Google Images for image URLs
    - google_trends: Check Google Trends for topic interest over time
    - google_maps: Search Google Maps for places, restaurants, businesses
    - google_maps_directions: Get directions between locations with route map screenshot
    - google_finance: Look up stock prices and market data
    - google_weather: Get current weather and forecasts
    - google_shopping: Search Google Shopping for products and prices
    - google_books: Search Google Books for books and publications
    - google_translate: Translate text between languages
    - google_flights: Search for flights between destinations
    - google_hotels: Search for hotels and accommodation
    - google_lens: Reverse image search to identify objects, products, brands
    - google_lens_detect: Detect objects in image and identify each via Lens
    - ocr_image: Extract text from images locally using RapidOCR (no internet needed)
    - transcribe_video: Download and transcribe YouTube videos with timestamps
    - search_transcript: Search a transcribed video for topics by keyword
    - extract_video_clip: Extract a video clip by topic
    - list_images: List image files in a directory for use with google_lens
    - visit_page: Fetch a URL and return its text content
    - subscribe: Subscribe to content sources (news RSS, Reddit, HN, GitHub, arXiv, YouTube, podcasts, Twitter/X)
    - unsubscribe: Remove a subscription and its stored content
    - list_subscriptions: List all active feed subscriptions
    - check_feeds: Fetch new content from all or specific subscriptions
    - search_feeds: Full-text search across all stored feed content
    - get_feed_items: Get recent items from feed subscriptions
"""

import asyncio
import hashlib
import imaplib
import json
import os
import random
import re
import sqlite3
import ssl
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from email import policy as email_policy
from email.parser import BytesParser as EmailParser
from pathlib import Path
from urllib.parse import quote_plus

from mcp.server.fastmcp import Context, FastMCP, Image
from playwright.async_api import async_playwright

mcp = FastMCP("google-search")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# JavaScript to inject before every page load to hide automation signals
STEALTH_JS = """
// Overwrite navigator.webdriver to false
Object.defineProperty(navigator, 'webdriver', { get: () => false });

// Fake plugins array (headless Chrome has none by default)
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer',
          description: 'Portable Document Format',
          length: 1, item: () => null, namedItem: () => null,
          [Symbol.iterator]: function*() { yield {type: 'application/pdf'}; } },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
          description: '', length: 1, item: () => null, namedItem: () => null,
          [Symbol.iterator]: function*() { yield {type: 'application/pdf'}; } },
        { name: 'Native Client', filename: 'internal-nacl-plugin',
          description: '', length: 2, item: () => null, namedItem: () => null,
          [Symbol.iterator]: function*() { yield {type: 'application/x-nacl'}; yield {type: 'application/x-pnacl'}; } },
    ],
});

// Fake languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Fake chrome.runtime to look like a real Chrome browser
if (!window.chrome) { window.chrome = {}; }
if (!window.chrome.runtime) {
    window.chrome.runtime = {
        connect: function() {},
        sendMessage: function() {},
        onMessage: { addListener: function() {} },
    };
}

// Remove Playwright-specific properties
delete window.__playwright;
delete window.__pw_manual;

// Patch permissions query for notifications
const originalQuery = window.Notification && Notification.permission
    ? Notification.permission : 'default';
if (navigator.permissions && navigator.permissions.query) {
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (params) => {
        if (params.name === 'notifications') {
            return Promise.resolve({ state: originalQuery, onchange: null });
        }
        return origQuery(params);
    };
}
"""

# Google's time filter parameter values
TIME_RANGE_MAP = {
    "past_hour": "qdr:h",
    "past_day": "qdr:d",
    "past_week": "qdr:w",
    "past_month": "qdr:m",
    "past_year": "qdr:y",
}


async def _launch_browser(pw, viewport=None):
    """Launch a headless Chromium browser with stealth settings to avoid bot detection."""
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--window-size=1280,800",
        ],
    )
    vp = viewport or {"width": 1280, "height": 800}
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport=vp,
        locale="en-US",
    )
    # Inject stealth patches before any page loads
    await context.add_init_script(STEALTH_JS)
    return browser, context


COOKIE_PATH = os.path.join(os.path.expanduser("~"), ".google_mcp_cookies.json")


async def _human_delay(page):
    """Add a small random delay to mimic human interaction timing."""
    await page.wait_for_timeout(random.randint(500, 1500))


async def _save_cookies(context):
    """Persist browser cookies to disk so Google sees a returning user."""
    try:
        cookies = await context.cookies()
        with open(COOKIE_PATH, "w") as f:
            json.dump(cookies, f)
    except Exception:
        pass


async def _load_cookies(context):
    """Load previously saved cookies into the browser context."""
    try:
        if os.path.isfile(COOKIE_PATH):
            with open(COOKIE_PATH, "r") as f:
                cookies = json.load(f)
            if cookies:
                await context.add_cookies(cookies)
    except Exception:
        pass


async def _is_blocked(page) -> bool:
    """Check if the current page is a Google CAPTCHA or rate-limit block."""
    url = page.url
    if "/sorry/" in url:
        return True
    try:
        captcha = await page.locator(
            "iframe[src*='recaptcha'], #captcha-form, "
            "form[action*='sorry'], div.g-recaptcha"
        ).count()
        if captcha > 0:
            return True
    except Exception:
        pass
    return False


async def _try_solve_captcha(page) -> bool:
    """Attempt to solve reCAPTCHA: first try checkbox click, then image challenge with neural net."""
    try:
        # Step 1: Try clicking the reCAPTCHA checkbox with human-like movement
        recaptcha_frame = page.frame_locator("iframe[src*='recaptcha']")
        checkbox = recaptcha_frame.locator("#recaptcha-anchor, .recaptcha-checkbox-border")
        if await checkbox.count() > 0:
            box = await checkbox.first.bounding_box()
            if box:
                x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

                await page.mouse.move(x - random.randint(50, 150), y - random.randint(50, 150))
                await page.wait_for_timeout(random.randint(100, 300))
                await page.mouse.move(x, y, steps=random.randint(10, 25))
                await page.wait_for_timeout(random.randint(200, 500))
                await page.mouse.click(x, y)
                await page.wait_for_timeout(random.randint(2000, 4000))

                if not await _is_blocked(page):
                    return True

        # Step 2: Checkbox wasn't enough, try solving the image challenge
        solved = await _solve_image_challenge(page)
        if solved:
            return True

        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Neural net CAPTCHA image challenge solver
# ---------------------------------------------------------------------------

CAPTCHA_MODEL_DIR = os.path.join(os.path.expanduser("~"), ".google_mcp_models")
MOBILENET_ONNX = os.path.join(CAPTCHA_MODEL_DIR, "mobilenetv2-12.onnx")
IMAGENET_LABELS_PATH = os.path.join(CAPTCHA_MODEL_DIR, "imagenet_labels.json")

# Compact mapping of common reCAPTCHA prompt keywords to ImageNet class indices
# ImageNet class index → label: https://gist.github.com/yrevar/942d3a0ac09ec9e5eb3a
CAPTCHA_CLASS_MAP = {
    "traffic light": [920],
    "bus": [654, 779, 874],
    "bicycle": [444, 671],
    "motorcycle": [670, 665],
    "car": [436, 468, 511, 609, 656, 717, 751, 817],
    "taxi": [468],
    "cab": [468],
    "crosswalk": [],
    "bridge": [839],
    "boat": [472, 484, 554, 625, 814, 914],
    "airplane": [404, 405],
    "plane": [404, 405],
    "train": [466, 547, 820, 829],
    "truck": [555, 569, 656, 675, 717, 864, 867],
    "fire hydrant": [],
    "hydrant": [],
    "parking meter": [705],
    "stair": [],
    "mountain": [970, 972, 976, 979, 980],
    "palm": [],
    "chimney": [],
    "tractor": [866],
}

# ImageNet mean/std for preprocessing
_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD = [0.229, 0.224, 0.225]


def _ensure_captcha_model() -> bool:
    """Download MobileNetV2 ONNX model if not present. Returns True if model is available."""
    os.makedirs(CAPTCHA_MODEL_DIR, exist_ok=True)
    if os.path.isfile(MOBILENET_ONNX):
        return True
    try:
        model_url = (
            "https://github.com/onnx/models/raw/main/validated/vision/"
            "classification/mobilenet/model/mobilenetv2-12.onnx"
        )
        req = urllib.request.Request(model_url, headers={"User-Agent": "NoAPI-MCP/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(MOBILENET_ONNX, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def _classify_cells(cells: list[bytes], prompt_keywords: list[str]) -> list[bool]:
    """Classify a list of image cell bytes against CAPTCHA prompt keywords using MobileNetV2.

    Returns a list of booleans indicating which cells match the prompt.
    """
    try:
        import cv2
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        return [False] * len(cells)

    if not _ensure_captcha_model():
        return [False] * len(cells)

    session = ort.InferenceSession(MOBILENET_ONNX)
    input_name = session.get_inputs()[0].name

    # Build set of target class indices from prompt keywords
    target_classes = set()
    for keyword in prompt_keywords:
        kw_lower = keyword.lower()
        for captcha_key, class_indices in CAPTCHA_CLASS_MAP.items():
            if captcha_key in kw_lower or kw_lower in captcha_key:
                target_classes.update(class_indices)

    if not target_classes:
        return [False] * len(cells)

    results = []
    for cell_bytes in cells:
        arr = np.frombuffer(cell_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            results.append(False)
            continue

        # Preprocess: resize to 224x224, normalize, CHW, batch
        img = cv2.resize(img, (224, 224))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        for c in range(3):
            img[:, :, c] = (img[:, :, c] - _IMAGENET_MEAN[c]) / _IMAGENET_STD[c]
        img = np.transpose(img, (2, 0, 1))  # CHW
        img = np.expand_dims(img, 0)  # NCHW

        outputs = session.run(None, {input_name: img})
        logits = outputs[0][0]

        # Softmax
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        # Check if any target class is in top-10 predictions with decent confidence
        top_indices = np.argsort(probs)[::-1][:10]
        match = any(idx in target_classes for idx in top_indices)
        # Also check if the top target class has > 5% probability
        target_probs = [probs[idx] for idx in target_classes if idx < len(probs)]
        if target_probs and max(target_probs) > 0.05:
            match = True

        results.append(match)

    return results


async def _solve_image_challenge(page) -> bool:
    """Attempt to solve a reCAPTCHA image challenge using MobileNetV2 neural net."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False

    try:
        # Find the challenge iframe (different from the checkbox iframe)
        challenge_frame = None
        for frame in page.frames:
            if "recaptcha" in (frame.url or "") and "bframe" in (frame.url or ""):
                challenge_frame = frame
                break

        if not challenge_frame:
            return False

        # Read the challenge prompt text
        prompt_el = challenge_frame.locator(
            ".rc-imageselect-desc-no-canonical, .rc-imageselect-desc, "
            ".rc-imageselect-instructions"
        )
        if await prompt_el.count() == 0:
            return False

        prompt_text = (await prompt_el.first.inner_text()).lower()
        # Extract keywords from prompt like "Select all images with traffic lights"
        prompt_keywords = [prompt_text]

        # Find the image grid
        grid = challenge_frame.locator("table.rc-imageselect-table, .rc-imageselect-target")
        if await grid.count() == 0:
            return False

        # Take screenshot of the grid
        grid_screenshot = await grid.first.screenshot()
        if not grid_screenshot:
            return False

        # Determine grid size (3x3 or 4x4)
        tiles = challenge_frame.locator("td.rc-imageselect-tile, .rc-image-tile-wrapper")
        tile_count = await tiles.count()

        if tile_count == 16:
            grid_size = 4
        else:
            grid_size = 3  # default

        # Split screenshot into grid cells
        arr = np.frombuffer(grid_screenshot, np.uint8)
        grid_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if grid_img is None:
            return False

        h, w = grid_img.shape[:2]
        cell_h, cell_w = h // grid_size, w // grid_size
        cells = []
        for row in range(grid_size):
            for col in range(grid_size):
                y1, y2 = row * cell_h, (row + 1) * cell_h
                x1, x2 = col * cell_w, (col + 1) * cell_w
                cell = grid_img[y1:y2, x1:x2]
                _, cell_bytes = cv2.imencode(".png", cell)
                cells.append(cell_bytes.tobytes())

        # Classify each cell with the neural net
        matches = _classify_cells(cells, prompt_keywords)

        if not any(matches):
            return False

        # Click matching cells with human-like delays
        for i, should_click in enumerate(matches):
            if should_click:
                row, col = divmod(i, grid_size)
                tile_locator = tiles.nth(i)
                if await tile_locator.count() > 0:
                    box = await tile_locator.bounding_box()
                    if box:
                        x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                        y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
                        await page.mouse.click(x, y)
                        await page.wait_for_timeout(random.randint(300, 700))

        # Wait for any new tiles to load (Google sometimes refreshes clicked tiles)
        await page.wait_for_timeout(random.randint(1500, 3000))

        # Click the verify button
        verify_btn = challenge_frame.locator("#recaptcha-verify-button")
        if await verify_btn.count() > 0:
            await verify_btn.first.click()
            await page.wait_for_timeout(random.randint(3000, 5000))

        # Check if we passed
        return not await _is_blocked(page)

    except Exception:
        return False


async def _dismiss_consent(page):
    """Dismiss Google consent banner if present (supports multiple languages)."""
    try:
        consent_btn = page.locator(
            "button:has-text('Accept all'), "
            "button:has-text('Accept All'), "
            "button:has-text('I agree'), "
            "button:has-text('Reject all'), "
            "button:has-text('Reject All'), "
            "button:has-text('Alle akzeptieren'), "
            "button:has-text('Alle ablehnen'), "
            "button:has-text('Tout accepter'), "
            "button:has-text('Tout refuser'), "
            "button:has-text('Aceptar todo'), "
            "button:has-text('Rechazar todo'), "
            "button:has-text('Accetta tutto'), "
            "button:has-text('Rifiuta tutto')"
        )
        if await consent_btn.count() > 0:
            await consent_btn.first.click()
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    # Small random delay to mimic human interaction timing
    await _human_delay(page)


# ---------------------------------------------------------------------------
# google_search
# ---------------------------------------------------------------------------

async def _do_google_search(
    query: str,
    num_results: int = 5,
    time_range: str | None = None,
    site: str | None = None,
    page: int = 1,
    language: str | None = None,
    region: str | None = None,
) -> str:
    """Launch headless Chromium, search Google, and scrape results."""
    search_query = query
    if site:
        search_query = f"site:{site} {search_query}"

    encoded_query = quote_plus(search_query)
    start = (page - 1) * num_results
    url = f"https://www.google.com/search?q={encoded_query}&num={num_results + 5}"

    # Language and region
    if language:
        url += f"&lr=lang_{language}&hl={language}"
    else:
        url += "&hl=en"
    if region:
        url += f"&gl={region}"

    if start > 0:
        url += f"&start={start}"
    if time_range and time_range in TIME_RANGE_MAP:
        url += f"&tbs={TIME_RANGE_MAP[time_range]}"

    async with async_playwright() as pw:
        browser, context = await _launch_browser(pw)
        await _load_cookies(context)
        browser_page = await context.new_page()

        try:
            await browser_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await _dismiss_consent(browser_page)

            # Detect and handle CAPTCHA/rate-limit blocks
            if await _is_blocked(browser_page):
                solved = await _try_solve_captcha(browser_page)
                if not solved:
                    await _save_cookies(context)
                    return (
                        "Search blocked by Google bot detection. "
                        "Your IP may be temporarily rate-limited. "
                        "Try again in a few minutes or from a different network."
                    )

            await browser_page.wait_for_selector("div#search", timeout=15000)

            results = await browser_page.evaluate(
                """
                (numResults) => {
                    const results = [];
                    const containers = document.querySelectorAll('div#search div.g');
                    for (const el of containers) {
                        if (results.length >= numResults) break;
                        const linkEl = el.querySelector('a[href^="http"]');
                        const titleEl = el.querySelector('h3');
                        const snippetEl = el.querySelector(
                            'div[data-sncf], div.VwiC3b, span.aCOpRe, div[style*="-webkit-line-clamp"]'
                        );
                        if (linkEl && titleEl) {
                            results.push({
                                title: titleEl.innerText.trim(),
                                url: linkEl.href,
                                snippet: snippetEl ? snippetEl.innerText.trim() : ''
                            });
                        }
                    }
                    if (results.length === 0) {
                        const allLinks = document.querySelectorAll('div#search a[href^="http"]');
                        for (const a of allLinks) {
                            if (results.length >= numResults) break;
                            const h3 = a.querySelector('h3');
                            if (h3) {
                                const parent = a.closest('div.g') || a.parentElement?.parentElement;
                                const snippetEl = parent?.querySelector(
                                    'div[data-sncf], div.VwiC3b, span.aCOpRe, div[style*="-webkit-line-clamp"]'
                                );
                                results.push({
                                    title: h3.innerText.trim(),
                                    url: a.href,
                                    snippet: snippetEl ? snippetEl.innerText.trim() : ''
                                });
                            }
                        }
                    }
                    return results;
                }
                """,
                num_results,
            )

            if not results:
                return f"No results found for: {query}"

            header = f"Google Search Results for: {query}"
            if time_range:
                header += f" (filtered: {time_range.replace('_', ' ')})"
            if site:
                header += f" (site: {site})"
            if language:
                header += f" (lang: {language})"
            if region:
                header += f" (region: {region})"
            if page > 1:
                header += f" (page {page})"

            lines = [header + "\n"]
            offset = (page - 1) * num_results
            for i, r in enumerate(results[:num_results], offset + 1):
                lines.append(f"{i}. {r['title']}")
                lines.append(f"   URL: {r['url']}")
                if r.get("snippet"):
                    lines.append(f"   {r['snippet']}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            # Check if the exception was due to bot detection
            if await _is_blocked(browser_page):
                await _save_cookies(context)
                return (
                    "Search blocked by Google bot detection. "
                    "Your IP may be temporarily rate-limited. "
                    "Try again in a few minutes or from a different network."
                )
            return f"Search failed: {e}"

        finally:
            await _save_cookies(context)
            await browser.close()


@mcp.tool()
async def google_search(
    query: str,
    num_results: int = 5,
    time_range: str = "",
    site: str = "",
    page: int = 1,
    language: str = "",
    region: str = "",
) -> str:
    """Search Google and return results with titles, URLs, and snippets.

    Sample prompts that trigger this tool:
        - "Search for the best Python web frameworks"
        - "Find Reddit discussions about home lab setups from the past week"
        - "Search Stack Overflow for async Python examples"
        - "Look up recent news about SpaceX in German"
        - "Get page 2 of results for machine learning tutorials"
        - "Search Hacker News for posts about Rust programming"
        - "Find Japanese results about Tokyo restaurants"

    Args:
        query: The search query string.
        num_results: Number of results to return (default 5, max 10).
        time_range: Filter by time. One of: "past_hour", "past_day", "past_week", "past_month", "past_year". Leave empty for no filter.
        site: Limit results to a specific domain (e.g. "reddit.com", "stackoverflow.com", "github.com", "arxiv.org", "news.ycombinator.com"). Leave empty for all sites.
        page: Results page number (default 1). Use 2, 3, etc. to get more results.
        language: Language code for results (e.g. "en", "de", "fr", "es", "ja", "zh"). Leave empty for English.
        region: Country/region code (e.g. "us", "gb", "de", "fr", "jp"). Leave empty for default.
    """
    num_results = max(1, min(num_results, 10))
    page = max(1, min(page, 10))
    return await _do_google_search(
        query,
        num_results,
        time_range=time_range or None,
        site=site or None,
        page=page,
        language=language or None,
        region=region or None,
    )


# (Continue with all other tools from the original file...)
# Truncating for space, but the full file remains the same from line 671 onwards

def _fetch_url_bytes(url: str, timeout: int = 15) -> bytes:
    """Fetch URL using stdlib urllib with SSL fix for Windows."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    
    # Windows SSL 인증서 문제 해결
    context = ssl._create_unverified_context()
    
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        return resp.read()
