"""
One Piece TCG Low Pop Alert Bot
Monitors eBay (via Finding API), Yahoo Auctions JP, TCGPlayer, Good Games AU
Sends Discord alerts for promo, prize, manga rare, and serialised cards
Runs as a GitHub Actions scheduled job
"""

import asyncio
import aiohttp
import json
import re
import logging
import os
import urllib.parse
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
EBAY_APP_ID = os.environ.get("EBAY_APP_ID", "")  # optional but recommended

SEARCH_GROUPS = {
    "🎴 Promo / Prize": [
        "one piece promo card",
        "one piece prize card",
        "one piece tournament winner card",
        "one piece finalist card",
        "one piece regional promo",
        "one piece championship card",
        "one piece treasure cup promo",
        "one piece store champion card",
        "one piece bandai fest promo",
        "one piece pre-release promo",
        "one piece worlds promo",
    ],
    "📖 Manga Rare": [
        "one piece manga rare",
        "one piece manga alt art",
        "one piece red manga rare",
        "one piece manga luffy",
        "one piece manga ace",
        "one piece manga sabo",
        "one piece OP13 manga",
        "ワンピース マンガレア",
        "ワンピース マンガ イラスト",
    ],
    "🔢 Serialised": [
        "one piece serial numbered card",
        "one piece serialized card",
        "one piece /700 card",
        "one piece /500 card",
        "one piece /100 card",
        "one piece numbered luffy",
        "one piece numbered roger",
        "ワンピース シリアル",
        "ワンピース 連番",
    ],
}

ALL_KEYWORDS = [kw for kws in SEARCH_GROUPS.values() for kw in kws]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Seen IDs ──────────────────────────────────────────────────────────────────

SEEN_FILE = Path("seen_ids.json")

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            pass
    return set()

def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(list(seen)[-5000:]))

# ── Relevance filter ──────────────────────────────────────────────────────────

MUST_INCLUDE = ["one piece", "ワンピース", "onepiece"]

PROMO_SIGNALS = [
    "promo", "prize", "winner", "finalist", "regional", "championship",
    "tournament", "pre-release", "prerelease", "treasure cup", "store champion",
    "worlds", "bandai fest", "serial", "numbered", "/700", "/500", "/100",
    "manga rare", "manga alt", "red manga", "manga luffy", "manga ace",
    "manga sabo", "manga zoro", "マンガレア", "プロモ", "優勝", "賞品",
    "大会", "予選", "店舗大会", "シリアル", "連番",
]

def is_relevant(title: str) -> bool:
    t = title.lower()
    if not any(kw in t for kw in MUST_INCLUDE):
        return False
    return any(sig in t for sig in PROMO_SIGNALS)

def get_group(title: str) -> str:
    t = title.lower()
    if any(s in t for s in ["manga rare", "manga alt", "red manga", "マンガレア", "マンガ"]):
        return "📖 Manga Rare"
    if any(s in t for s in ["serial", "numbered", "/700", "/500", "/100", "シリアル", "連番"]):
        return "🔢 Serialised"
    return "🎴 Promo / Prize"

# ── Discord ───────────────────────────────────────────────────────────────────

COLOUR_MAP = {
    "📖 Manga Rare": 0x9B59B6,
    "🔢 Serialised": 0xF39C12,
    "🎴 Promo / Prize": 0xE8272C,
}

async def send_discord(session: aiohttp.ClientSession, listing: dict):
    group = listing.get("group", "🎴 Promo / Prize")
    colour = COLOUR_MAP.get(group, 0xE8272C)
    platform_emoji = {
        "eBay AU": "🛒",
        "Yahoo Auctions JP": "🇯🇵",
        "TCGPlayer": "🃏",
        "Good Games AU": "🦘",
    }.get(listing.get("platform", ""), "📦")

    embed = {
        "title": f"{platform_emoji} {listing['title'][:200]}",
        "url": listing.get("url", ""),
        "color": colour,
        "fields": [
            {"name": "💰 Price", "value": listing.get("price", "N/A"), "inline": True},
            {"name": "🏪 Platform", "value": listing.get("platform", "?"), "inline": True},
            {"name": "📂 Category", "value": group, "inline": True},
        ],
        "footer": {"text": f"OP Alert Bot • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
    }

    try:
        async with session.post(DISCORD_WEBHOOK, json={"embeds": [embed]}) as resp:
            if resp.status in (200, 204):
                log.info(f"✅ [{group}] {listing['title'][:60]}")
            else:
                log.error(f"Discord {resp.status}: {await resp.text()}")
        await asyncio.sleep(0.5)
    except Exception as e:
        log.error(f"Discord error: {e}")

# ── eBay ──────────────────────────────────────────────────────────────────────

async def scrape_ebay(session: aiohttp.ClientSession, keyword: str) -> list:
    results = []

    if EBAY_APP_ID:
        params = {
            "OPERATION-NAME": "findItemsByKeywords",
            "SERVICE-VERSION": "1.0.0",
            "SECURITY-APPNAME": EBAY_APP_ID,
            "RESPONSE-DATA-FORMAT": "JSON",
            "keywords": keyword,
            "categoryId": "2536",
            "itemFilter(0).name": "ListingType",
            "itemFilter(0).value(0)": "FixedPrice",
            "itemFilter(0).value(1)": "Auction",
            "paginationInput.entriesPerPage": "50",
            "sortOrder": "StartTimeNewest",
        }
        url = "https://svcs.ebay.com/services/search/FindingService/v1?" + urllib.parse.urlencode(params)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    items = (
                        data.get("findItemsByKeywordsResponse", [{}])[0]
                        .get("searchResult", [{}])[0]
                        .get("item", [])
                    )
                    for item in items:
                        title = item.get("title", [""])[0]
                        sp = item.get("sellingStatus", [{}])[0].get("currentPrice", [{}])[0]
                        price = sp.get("__value__", "N/A")
                        currency = sp.get("@currencyId", "")
                        url_val = item.get("viewItemURL", [""])[0]
                        item_id = item.get("itemId", [""])[0]
                        if title and item_id:
                            results.append({
                                "id": f"ebay_{item_id}",
                                "title": title,
                                "price": f"{currency} {price}",
                                "url": url_val,
                                "platform": "eBay AU",
                            })
        except Exception as e:
            log.warning(f"eBay API error ({keyword}): {e}")
    else:
        # RSS fallback — more reliable than HTML scraping
        encoded = urllib.parse.quote(keyword)
        url = f"https://www.ebay.com.au/srch/rss?_nkw={encoded}&LH_BIN=1&_sop=10"
        try:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    try:
                        root = ET.fromstring(text)
                        ns = {"g": "http://base.google.com/ns/1.0"}
                        for item in root.findall(".//item"):
                            title_el = item.find("title")
                            link_el = item.find("link")
                            price_el = item.find("g:price", ns)
                            guid_el = item.find("guid")
                            title = title_el.text if title_el is not None else ""
                            link = link_el.text if link_el is not None else ""
                            price = price_el.text if price_el is not None else "N/A"
                            guid = guid_el.text if guid_el is not None else link
                            if title and link:
                                item_id = re.search(r"/itm/(\d+)", link)
                                results.append({
                                    "id": f"ebay_{item_id.group(1) if item_id else abs(hash(guid))}",
                                    "title": title,
                                    "price": f"A${price}" if price != "N/A" else "N/A",
                                    "url": link,
                                    "platform": "eBay AU",
                                })
                    except ET.ParseError:
                        # Last resort: regex on raw RSS
                        for title, link in zip(
                            re.findall(r'<title><!\[CDATA\[([^\]]+)\]\]></title>', text)[1:],
                            re.findall(r'<link>([^<]+)</link>', text)[1:],
                        ):
                            item_id = re.search(r"/itm/(\d+)", link)
                            results.append({
                                "id": f"ebay_{item_id.group(1) if item_id else abs(hash(link))}",
                                "title": title,
                                "price": "N/A",
                                "url": link,
                                "platform": "eBay AU",
                            })
        except Exception as e:
            log.warning(f"eBay RSS error ({keyword}): {e}")

    return results

# ── Yahoo Auctions JP ─────────────────────────────────────────────────────────

async def scrape_yahoo_jp(session: aiohttp.ClientSession, keyword: str) -> list:
    results = []
    encoded = urllib.parse.quote(keyword)
    url = f"https://auctions.yahoo.co.jp/search/search;_ylt=A2RimXFm?p={encoded}&b=1&n=50&s1=new&o1=d&mode=2&format=rss"
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.9"},
            timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                return results
            text = await resp.text(encoding="utf-8", errors="replace")

        try:
            root = ET.fromstring(text)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                title = title_el.text if title_el is not None else ""
                link = link_el.text if link_el is not None else ""
                desc = desc_el.text if desc_el is not None else ""
                price_m = re.search(r'現在価格.*?([\d,]+)円', desc or "")
                price = f"¥{price_m.group(1)}" if price_m else "N/A"
                item_id = re.search(r'[a-zA-Z]\d{9,}', link or "")
                if title and link:
                    results.append({
                        "id": f"yahoo_{item_id.group(0) if item_id else abs(hash(link))}",
                        "title": title,
                        "price": price,
                        "url": link,
                        "platform": "Yahoo Auctions JP",
                    })
        except ET.ParseError:
            titles = re.findall(r'<title><!\[CDATA\[([^\]]+)\]\]></title>', text)
            links = re.findall(r'<link>([^<]+)</link>', text)
            prices = re.findall(r'現在価格.*?([\d,]+)円', text)
            for i, (t, l) in enumerate(zip(titles[2:], links[2:])):
                item_id = re.search(r'[a-zA-Z]\d{9,}', l)
                results.append({
                    "id": f"yahoo_{item_id.group(0) if item_id else abs(hash(l))}",
                    "title": t,
                    "price": f"¥{prices[i]}" if i < len(prices) else "N/A",
                    "url": l,
                    "platform": "Yahoo Auctions JP",
                })
    except Exception as e:
        log.warning(f"Yahoo JP error ({keyword}): {e}")
    return results

# ── TCGPlayer ─────────────────────────────────────────────────────────────────

async def scrape_tcgplayer(session: aiohttp.ClientSession, keyword: str) -> list:
    results = []
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.tcgplayer.com/search/one-piece-card-game/product?q={encoded}&view=grid&inStock=true"
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"},
            timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                return results
            html = await resp.text()

        # Try Next.js data blob
        json_m = re.search(r'id="__NEXT_DATA__"[^>]*>(\{.+?\})</script>', html, re.DOTALL)
        if json_m:
            try:
                data = json.loads(json_m.group(1))
                products = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("results", [])
                )
                for p in products[:20]:
                    name = p.get("productName") or p.get("name", "")
                    price = p.get("marketPrice") or p.get("lowestPrice")
                    prod_id = p.get("productId", abs(hash(name)))
                    slug = p.get("urlKey") or p.get("productUrlKey", "")
                    if name:
                        results.append({
                            "id": f"tcp_{prod_id}",
                            "title": f"One Piece {name}",
                            "price": f"${float(price):.2f}" if price else "N/A",
                            "url": f"https://www.tcgplayer.com/product/{prod_id}/{slug}",
                            "platform": "TCGPlayer",
                        })
            except Exception:
                pass
    except Exception as e:
        log.warning(f"TCGPlayer error ({keyword}): {e}")
    return results

# ── Good Games AU ─────────────────────────────────────────────────────────────

async def scrape_goodgames(session: aiohttp.ClientSession, keyword: str) -> list:
    results = []
    encoded = urllib.parse.quote(keyword)
    url = f"https://goodgames.com.au/search?type=product&q={encoded}"
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                return results
            html = await resp.text()

        # Shopify stores product JSON in a script tag
        for json_m in re.finditer(r'<script type="application/json"[^>]*>(\[.+?\])</script>', html, re.DOTALL):
            try:
                products = json.loads(json_m.group(1))
                if not isinstance(products, list):
                    continue
                for p in products[:10]:
                    name = p.get("title", "")
                    price = None
                    variants = p.get("variants", [])
                    if variants:
                        price = variants[0].get("price")
                    handle = p.get("handle", "")
                    prod_id = p.get("id", abs(hash(name)))
                    if name and "one piece" in name.lower():
                        results.append({
                            "id": f"gg_{prod_id}",
                            "title": name,
                            "price": f"A${float(price)/100:.2f}" if price else "N/A",
                            "url": f"https://goodgames.com.au/products/{handle}",
                            "platform": "Good Games AU",
                        })
            except Exception:
                continue
    except Exception as e:
        log.warning(f"Good Games error ({keyword}): {e}")
    return results

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log.info("🏴‍☠️ OP Alert Bot starting")

    if not DISCORD_WEBHOOK:
        log.error("DISCORD_WEBHOOK secret not set")
        return

    seen = load_seen()
    new_seen = set()
    alerts_sent = 0

    async with aiohttp.ClientSession() as session:

        # Startup ping
        await session.post(DISCORD_WEBHOOK, json={"embeds": [{
            "title": "🏴‍☠️ OP Bot scan started",
            "description": "Scanning for: **🎴 Promo/Prize · 📖 Manga Rare · 🔢 Serialised**\nPlatforms: eBay AU · Yahoo Auctions JP · TCGPlayer · Good Games AU",
            "color": 0x2ECC71,
            "footer": {"text": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
        }]})

        en_keywords = [kw for kw in ALL_KEYWORDS if not any(ord(c) > 127 for c in kw)]
        jp_keywords = [kw for kw in ALL_KEYWORDS if any(ord(c) > 127 for c in kw)]

        all_listings = []

        for kw in en_keywords:
            log.info(f"EN: {kw}")
            all_listings += await scrape_ebay(session, kw)
            all_listings += await scrape_tcgplayer(session, kw)
            all_listings += await scrape_goodgames(session, kw)
            await asyncio.sleep(1.5)

        for kw in jp_keywords:
            log.info(f"JP: {kw}")
            all_listings += await scrape_yahoo_jp(session, kw)
            await asyncio.sleep(1.5)

        # Also search Yahoo in English for cross-market finds
        for kw in ["one piece manga rare", "one piece serial numbered", "one piece promo prize"]:
            all_listings += await scrape_yahoo_jp(session, kw)
            await asyncio.sleep(1)

        log.info(f"{len(all_listings)} raw listings — filtering")

        seen_this_run = set()
        for listing in all_listings:
            lid = listing["id"]
            if lid in seen or lid in seen_this_run:
                continue
            seen_this_run.add(lid)
            if not is_relevant(listing["title"]):
                continue
            listing["group"] = get_group(listing["title"])
            await send_discord(session, listing)
            new_seen.add(lid)
            alerts_sent += 1

        await session.post(DISCORD_WEBHOOK, json={"embeds": [{
            "title": "✅ Scan complete",
            "description": (
                f"**{alerts_sent}** new alerts sent\n"
                f"**{len(all_listings)}** listings checked\n"
                f"**{len(seen | new_seen)}** IDs tracked"
            ),
            "color": 0x3498DB,
            "footer": {"text": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
        }]})

    save_seen(seen | new_seen)
    log.info(f"Done — {alerts_sent} alerts sent")

if __name__ == "__main__":
    asyncio.run(main())
