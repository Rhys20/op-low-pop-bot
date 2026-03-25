"""
One Piece TCG Low Pop Alert Bot
Monitors eBay, Yahoo Auctions JP, TCGPlayer, Good Games AU, Eternal Games
Sends Discord alerts when promo/prize cards with low PSA pop appear
"""

import asyncio
import aiohttp
import json
import re
import time
import logging
from datetime import datetime
from config import CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Track seen listing IDs to avoid duplicate alerts ──
seen_ids: set = set()

# ─────────────────────────────────────────────────────
# DISCORD
# ─────────────────────────────────────────────────────

async def send_discord(session: aiohttp.ClientSession, listing: dict):
    """Send a rich Discord embed for a matching listing."""
    color = {
        "ebay_bin":   0xE8C84A,
        "ebay_auc":   0xFF6B35,
        "yahoo":      0x4AB8FF,
        "tcgplayer":  0x4ADF8A,
        "goodgames":  0xA78BFA,
        "eternal":    0xFF5566,
    }.get(listing.get("source", ""), 0xE8C84A)

    platform_label = {
        "ebay_bin":  "eBay — Buy It Now",
        "ebay_auc":  "eBay — Auction",
        "yahoo":     "Yahoo Auctions Japan",
        "tcgplayer": "TCGPlayer",
        "goodgames": "Good Games AU",
        "eternal":   "Eternal Games",
    }.get(listing.get("source", ""), listing.get("source", "Unknown"))

    price_str = listing.get("price_str", "—")
    pop = listing.get("pop")
    pop_str = f"PSA 10 pop: {pop}" if pop is not None else "Pop: not checked"

    fields = [
        {"name": "💰 Price", "value": price_str, "inline": True},
        {"name": "📊 " + pop_str, "value": "\u200b", "inline": True},
        {"name": "🏪 Platform", "value": platform_label, "inline": True},
    ]
    if listing.get("condition"):
        fields.append({"name": "Condition", "value": listing["condition"], "inline": True})
    if listing.get("ends_at"):
        fields.append({"name": "⏰ Ends", "value": listing["ends_at"], "inline": True})

    embed = {
        "title": f"🚨 {listing['title'][:200]}",
        "url": listing["url"],
        "color": color,
        "fields": fields,
        "footer": {"text": f"OP Low Pop Bot • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
    }
    if listing.get("image"):
        embed["thumbnail"] = {"url": listing["image"]}

    payload = {
        "username": "OP Low Pop Scanner",
        "avatar_url": "https://optcgapi.com/media/static/Card_Images/OP01-003.jpg",
        "embeds": [embed],
    }

    try:
        async with session.post(CONFIG["discord_webhook"], json=payload) as r:
            if r.status in (200, 204):
                log.info(f"✅ Alert sent: {listing['title'][:60]}")
            else:
                body = await r.text()
                log.warning(f"Discord returned {r.status}: {body[:200]}")
    except Exception as e:
        log.error(f"Discord send error: {e}")


# ─────────────────────────────────────────────────────
# POP CHECKER (PriceCharting)
# ─────────────────────────────────────────────────────

async def get_pop(session: aiohttp.ClientSession, card_name: str) -> int | None:
    """Try to get PSA 10 pop from PriceCharting. Returns None if unavailable."""
    try:
        url = f"https://www.pricecharting.com/search-products?q={aiohttp.helpers.requote_uri('one piece ' + card_name)}&type=prices"
        headers = {"User-Agent": CONFIG["user_agent"]}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return None
            html = await r.text()
            m = re.search(r'PSA 10[^<]*<[^>]*>\s*([0-9,]+)', html)
            if m:
                return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────
# KEYWORD MATCHING
# ─────────────────────────────────────────────────────

def is_relevant(title: str) -> bool:
    """Return True if this listing matches our target keywords."""
    t = title.lower()
    # Must contain One Piece indicator
    if not any(k in t for k in ["one piece", "ワンピース", "onepiece"]):
        return False
    # Must contain a promo/prize/low-pop indicator
    promo_keys = [
        "promo", "prize", "winner", "finalist", "regional", "championship",
        "tournament", "pre-release", "pre release", "store champion",
        "treasure cup", "bandai fest", "worlds", "world championship",
        "優勝", "プロモ", "大会", "予選", "決勝", "店舗大会",
    ]
    return any(k in t for k in promo_keys)


# ─────────────────────────────────────────────────────
# eBay
# ─────────────────────────────────────────────────────

async def scrape_ebay(session: aiohttp.ClientSession, mode: str = "bin") -> list[dict]:
    """
    mode: 'bin' = Buy It Now, 'auc' = Auctions ending soon
    Uses eBay Browse API (no OAuth needed for basic search).
    Falls back to HTML scrape if API key not set.
    """
    results = []
    source = f"ebay_{mode}"

    for keyword in CONFIG["keywords"]:
        try:
            if CONFIG.get("ebay_app_id"):
                results += await _ebay_api(session, keyword, mode, source)
            else:
                results += await _ebay_html(session, keyword, mode, source)
            await asyncio.sleep(0.5)
        except Exception as e:
            log.warning(f"eBay ({mode}) error for '{keyword}': {e}")

    return results


async def _ebay_api(session, keyword, mode, source):
    """eBay Browse API search."""
    results = []
    filter_str = "buyingOptions:{FIXED_PRICE}" if mode == "bin" else "buyingOptions:{AUCTION}"
    params = {
        "q": f"one piece {keyword}",
        "filter": filter_str,
        "sort": "newlyListed" if mode == "bin" else "endingSoonest",
        "limit": "50",
    }
    headers = {
        "Authorization": f"Bearer {CONFIG['ebay_app_id']}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    async with session.get(url, params=params, headers=headers,
                           timeout=aiohttp.ClientTimeout(total=15)) as r:
        if r.status != 200:
            return results
        data = await r.json()
        for item in data.get("itemSummaries", []):
            lid = f"ebay_{item.get('itemId','')}"
            if lid in seen_ids:
                continue
            title = item.get("title", "")
            if not is_relevant(title):
                continue
            price = item.get("price", {})
            price_str = f"{price.get('currency','USD')} {price.get('value','?')}"
            results.append({
                "id": lid,
                "title": title,
                "url": item.get("itemWebUrl", ""),
                "price_str": price_str,
                "image": (item.get("image") or {}).get("imageUrl"),
                "condition": item.get("condition", ""),
                "source": source,
            })
    return results


async def _ebay_html(session, keyword, mode, source):
    """Fallback: scrape eBay search HTML."""
    results = []
    sort = "15" if mode == "bin" else "1"
    lh = "LH_BIN=1" if mode == "bin" else "LH_Auction=1&LH_Complete=0"
    url = (f"https://www.ebay.com/sch/i.html"
           f"?_nkw={aiohttp.helpers.requote_uri('one piece ' + keyword)}"
           f"&_sop={sort}&{lh}&_ipg=60")
    headers = {"User-Agent": CONFIG["user_agent"]}
    async with session.get(url, headers=headers,
                           timeout=aiohttp.ClientTimeout(total=15)) as r:
        if r.status != 200:
            return results
        html = await r.text()

    # Extract item titles and links
    items = re.findall(
        r'<div class="s-item__info[^"]*".*?'
        r'href="(https://www\.ebay\.com/itm/[^"]+)".*?'
        r'<div class="s-item__title[^"]*"[^>]*>(.*?)</div>.*?'
        r's-item__price[^>]*>(.*?)</span',
        html, re.DOTALL
    )
    for url_i, title_raw, price_raw in items[:30]:
        title = re.sub(r'<[^>]+>', '', title_raw).strip()
        price = re.sub(r'<[^>]+>', '', price_raw).strip()
        if not title or "Shop on eBay" in title:
            continue
        if not is_relevant(title):
            continue
        # Use URL as ID
        item_id_m = re.search(r'/itm/(\d+)', url_i)
        lid = f"ebay_{item_id_m.group(1)}" if item_id_m else f"ebay_{hash(url_i)}"
        if lid in seen_ids:
            continue
        results.append({
            "id": lid,
            "title": title,
            "url": url_i.split("?")[0],
            "price_str": price,
            "source": source,
        })
    return results


# ─────────────────────────────────────────────────────
# Yahoo Auctions Japan
# ─────────────────────────────────────────────────────

async def scrape_yahoo(session: aiohttp.ClientSession) -> list[dict]:
    results = []
    jp_keywords = CONFIG.get("jp_keywords", ["ワンピース プロモ", "ワンピース 優勝", "ワンピース 大会 賞品"])

    for kw in jp_keywords:
        try:
            url = (f"https://auctions.yahoo.co.jp/search/search"
                   f"?p={aiohttp.helpers.requote_uri(kw)}"
                   f"&s1=end&o1=a&fmt=2&b=1&n=40")
            headers = {"User-Agent": CONFIG["user_agent"]}
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    continue
                html = await r.text()

            # Parse auction items
            auctions = re.findall(
                r'<div class="Product__detail.*?'
                r'href="(https://page\.auctions\.yahoo\.co\.jp/jp/auction/[^"]+)".*?'
                r'class="Product__title[^"]*"[^>]*>(.*?)</p.*?'
                r'class="Product__price[^"]*"[^>]*>(.*?)</span',
                html, re.DOTALL
            )
            for auc_url, title_raw, price_raw in auctions[:20]:
                title = re.sub(r'<[^>]+>', '', title_raw).strip()
                price = re.sub(r'<[^>]+>', '', price_raw).strip()
                lid = f"yahoo_{hash(auc_url)}"
                if lid in seen_ids:
                    continue
                if not title:
                    continue
                results.append({
                    "id": lid,
                    "title": f"[JP] {title}",
                    "url": auc_url,
                    "price_str": f"¥{price}" if price and not price.startswith("¥") else price,
                    "source": "yahoo",
                })
            await asyncio.sleep(1)
        except Exception as e:
            log.warning(f"Yahoo error for '{kw}': {e}")

    return results


# ─────────────────────────────────────────────────────
# TCGPlayer
# ─────────────────────────────────────────────────────

async def scrape_tcgplayer(session: aiohttp.ClientSession) -> list[dict]:
    results = []
    for keyword in CONFIG["keywords"]:
        try:
            url = (f"https://www.tcgplayer.com/search/one-piece-card-game/product"
                   f"?q={aiohttp.helpers.requote_uri(keyword)}"
                   f"&view=grid&productLineName=one-piece-card-game&inStock=true")
            headers = {
                "User-Agent": CONFIG["user_agent"],
                "Accept": "text/html",
            }
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    continue
                html = await r.text()

            # Extract product cards from TCGPlayer HTML
            products = re.findall(
                r'"productName":"([^"]+)".*?"marketPrice":([0-9.]+).*?"productUrl":"([^"]+)"',
                html
            )
            for title, price, purl in products[:20]:
                if not is_relevant(title):
                    continue
                lid = f"tcg_{hash(purl)}"
                if lid in seen_ids:
                    continue
                results.append({
                    "id": lid,
                    "title": title,
                    "url": f"https://www.tcgplayer.com{purl}" if purl.startswith("/") else purl,
                    "price_str": f"USD {price}",
                    "source": "tcgplayer",
                })
            await asyncio.sleep(0.5)
        except Exception as e:
            log.warning(f"TCGPlayer error for '{keyword}': {e}")
    return results


# ─────────────────────────────────────────────────────
# Good Games Australia
# ─────────────────────────────────────────────────────

async def scrape_goodgames(session: aiohttp.ClientSession) -> list[dict]:
    results = []
    try:
        for keyword in CONFIG["keywords"]:
            url = (f"https://www.goodgames.com.au/search?q="
                   f"{aiohttp.helpers.requote_uri('one piece ' + keyword)}"
                   f"&type=product")
            headers = {"User-Agent": CONFIG["user_agent"]}
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    continue
                html = await r.text()

            # Good Games uses Shopify — parse product JSON
            products = re.findall(
                r'"title":"([^"]+)".*?"url":"(/products/[^"]+)".*?"price":(\d+)',
                html
            )
            for title, path, price_cents in products[:20]:
                if not is_relevant(title):
                    continue
                lid = f"gg_{hash(path)}"
                if lid in seen_ids:
                    continue
                price_aud = int(price_cents) / 100
                results.append({
                    "id": lid,
                    "title": title,
                    "url": f"https://www.goodgames.com.au{path}",
                    "price_str": f"AUD {price_aud:.2f}",
                    "source": "goodgames",
                })
            await asyncio.sleep(0.5)
    except Exception as e:
        log.warning(f"Good Games error: {e}")
    return results


# ─────────────────────────────────────────────────────
# Eternal Games
# ─────────────────────────────────────────────────────

async def scrape_eternal(session: aiohttp.ClientSession) -> list[dict]:
    results = []
    try:
        for keyword in CONFIG["keywords"]:
            url = (f"https://eternalmagic.com.au/search?type=product"
                   f"&q={aiohttp.helpers.requote_uri('one piece ' + keyword)}")
            headers = {"User-Agent": CONFIG["user_agent"]}
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    continue
                html = await r.text()

            products = re.findall(
                r'"title":"([^"]+)".*?"url":"(/products/[^"]+)".*?"price":(\d+)',
                html
            )
            for title, path, price_cents in products[:20]:
                if not is_relevant(title):
                    continue
                lid = f"eternal_{hash(path)}"
                if lid in seen_ids:
                    continue
                price_aud = int(price_cents) / 100
                results.append({
                    "id": lid,
                    "title": title,
                    "url": f"https://eternalmagic.com.au{path}",
                    "price_str": f"AUD {price_aud:.2f}",
                    "source": "eternal",
                })
            await asyncio.sleep(0.5)
    except Exception as e:
        log.warning(f"Eternal Games error: {e}")
    return results


# ─────────────────────────────────────────────────────
# MAIN SCAN LOOP
# ─────────────────────────────────────────────────────

async def run_scan():
    """Run one full scan cycle across all platforms."""
    log.info("── Starting scan cycle ──")
    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:

        # Gather all listings
        all_listings = []
        all_listings += await scrape_ebay(session, "bin")
        all_listings += await scrape_ebay(session, "auc")
        all_listings += await scrape_yahoo(session)
        all_listings += await scrape_tcgplayer(session)
        all_listings += await scrape_goodgames(session)
        all_listings += await scrape_eternal(session)

        log.info(f"Found {len(all_listings)} candidate listings")

        alerted = 0
        for listing in all_listings:
            lid = listing["id"]
            if lid in seen_ids:
                continue

            # Check pop if enabled
            pop = None
            if CONFIG.get("check_pop", True):
                pop = await get_pop(session, listing["title"])
                listing["pop"] = pop
                await asyncio.sleep(0.3)

            # Apply pop filter
            pop_threshold = CONFIG.get("pop_threshold", 100)
            if pop is not None and pop > pop_threshold:
                log.debug(f"Skipping (pop {pop} > {pop_threshold}): {listing['title'][:50]}")
                seen_ids.add(lid)
                continue

            # Send alert
            await send_discord(session, listing)
            seen_ids.add(lid)
            alerted += 1
            await asyncio.sleep(0.5)  # Rate limit Discord

        log.info(f"── Scan complete. {alerted} alerts sent ──")

        # Keep seen_ids from growing unbounded (keep last 5000)
        if len(seen_ids) > 5000:
            to_remove = list(seen_ids)[:1000]
            for item in to_remove:
                seen_ids.discard(item)


async def main():
    log.info("🏴‍☠️  One Piece Low Pop Bot starting...")
    log.info(f"   Pop threshold : PSA 10 pop < {CONFIG['pop_threshold']}")
    log.info(f"   Scan interval : every {CONFIG['scan_interval_minutes']} minutes")
    log.info(f"   Keywords      : {', '.join(CONFIG['keywords'])}")

    # Send startup message to Discord
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        payload = {
            "username": "OP Low Pop Scanner",
            "content": (
                f"🏴‍☠️ **One Piece Low Pop Bot is live!**\n"
                f"Monitoring eBay, Yahoo JP, TCGPlayer, Good Games AU & Eternal Games\n"
                f"Pop threshold: PSA 10 pop < {CONFIG['pop_threshold']}\n"
                f"Scanning every {CONFIG['scan_interval_minutes']} minutes"
            )
        }
        try:
            async with session.post(CONFIG["discord_webhook"], json=payload) as r:
                if r.status in (200, 204):
                    log.info("✅ Startup message sent to Discord")
        except Exception as e:
            log.error(f"Could not send startup message: {e}")

    # Main loop
    while True:
        try:
            await run_scan()
        except Exception as e:
            log.error(f"Scan cycle error: {e}")
        interval = CONFIG["scan_interval_minutes"] * 60
        log.info(f"💤 Sleeping {CONFIG['scan_interval_minutes']} minutes...")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
