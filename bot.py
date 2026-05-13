"""
One Piece TCG Low Pop Alert Bot
Monitors eBay, Yahoo Auctions JP, TCGPlayer, Good Games AU, Eternal Games
Sends Discord alerts when promo/prize cards with low PSA pop appear
Designed to run as a GitHub Actions scheduled job
"""

import asyncio
import aiohttp
import json
import re
import logging
import os
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DISCORD_WEBHOOK = os.environ.get(
    "DISCORD_WEBHOOK",
    "https://discord.com/api/webhooks/1504115906081722368/pCGcJ9PBlZOfgYMSXBOWQuCcIeLiF2rrAabXLv13p95Ezfrxw7Xk_FuQx7TBQVRc6xW6"
)

POP_THRESHOLD = 100  # Alert when PSA 10 pop is below this number
CHECK_POP = False    # Set True to filter by pop (slower, more API calls)

KEYWORDS = [
    "one piece promo",
    "one piece prize card",
    "one piece winner",
    "one piece finalist",
    "one piece regional promo",
    "one piece championship promo",
    "one piece tournament winner",
    "one piece pre-release promo",
    "one piece treasure cup",
    "one piece store champion",
    "one piece worlds promo",
    "one piece bandai fest",
    "one piece serial",
]

JP_KEYWORDS = [
    "ワンピース プロモ",
    "ワンピース 優勝",
    "ワンピース 大会 賞品",
    "ワンピース 地区予選",
    "ワンピース 決勝",
    "ワンピース 店舗大会",
    "ワンピース プレリリース",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ── Seen IDs (persisted in seen_ids.json in repo) ────────────────────────────

SEEN_FILE = Path("seen_ids.json")

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            pass
    return set()

def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(list(seen)))

# ── Discord ───────────────────────────────────────────────────────────────────

async def send_discord(session: aiohttp.ClientSession, listing: dict):
    """Send a rich Discord embed for a matching listing."""
    platform_emoji = {
        "eBay": "🛒",
        "Yahoo Auctions JP": "🇯🇵",
        "TCGPlayer": "🃏",
        "Good Games AU": "🦘",
        "Eternal Games": "⚔️",
    }.get(listing.get("platform", ""), "📦")

    price_str = listing.get("price", "N/A")
    pop_str = f"PSA 10 pop: {listing['pop']}" if listing.get("pop") else ""

    embed = {
        "title": f"{platform_emoji} {listing['title'][:200]}",
        "url": listing.get("url", ""),
        "color": 0xE8272C,
        "fields": [
            {"name": "💰 Price", "value": price_str, "inline": True},
            {"name": "🏪 Platform", "value": listing.get("platform", "Unknown"), "inline": True},
        ],
        "footer": {"text": f"OP Low Pop Bot • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
    }

    if pop_str:
        embed["fields"].append({"name": "📊 Population", "value": pop_str, "inline": True})

    payload = {"embeds": [embed]}

    try:
        async with session.post(DISCORD_WEBHOOK, json=payload) as resp:
            if resp.status in (200, 204):
                log.info(f"✅ Alert sent: {listing['title'][:60]}")
            else:
                text = await resp.text()
                log.error(f"Discord error {resp.status}: {text}")
    except Exception as e:
        log.error(f"Discord send failed: {e}")

# ── eBay scraper ──────────────────────────────────────────────────────────────

async def scrape_ebay(session: aiohttp.ClientSession, keyword: str) -> list:
    results = []
    url = (
        f"https://www.ebay.com.au/sch/i.html?_nkw={keyword.replace(' ', '+')}"
        f"&_sop=10&LH_BIN=1&_ipg=50"
    )
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return results
            html = await resp.text()

        # Extract listings
        items = re.findall(
            r'<li[^>]+s-item[^>]*>.*?</li>',
            html, re.DOTALL
        )
        for item in items[:20]:
            title_m = re.search(r'class="s-item__title[^"]*"[^>]*>([^<]+)', item)
            price_m = re.search(r'class="s-item__price[^"]*"[^>]*>\s*<span[^>]*>([^<]+)', item)
            link_m = re.search(r'href="(https://www\.ebay\.[^"]+/itm/[^"?]+)', item)
            id_m = re.search(r'/itm/(\d+)', item)

            if not (title_m and link_m and id_m):
                continue

            title = title_m.group(1).strip()
            if "Shop on eBay" in title or not title:
                continue

            results.append({
                "id": f"ebay_{id_m.group(1)}",
                "title": title,
                "price": price_m.group(1).strip() if price_m else "N/A",
                "url": link_m.group(1),
                "platform": "eBay",
            })
    except Exception as e:
        log.warning(f"eBay scrape error ({keyword}): {e}")
    return results

# ── Yahoo Auctions JP scraper ─────────────────────────────────────────────────

async def scrape_yahoo_jp(session: aiohttp.ClientSession, keyword: str) -> list:
    results = []
    url = f"https://auctions.yahoo.co.jp/search/search?p={keyword.replace(' ', '+')}&va={keyword.replace(' ', '+')}&exflg=1&b=1&n=50"
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return results
            html = await resp.text()

        items = re.findall(r'<div class="Product".*?</div>\s*</div>', html, re.DOTALL)
        for item in items[:20]:
            title_m = re.search(r'class="Product__title[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', item, re.DOTALL)
            price_m = re.search(r'class="Product__price[^"]*"[^>]*>.*?<span[^>]*>([\d,]+)', item, re.DOTALL)
            link_m = re.search(r'href="(https://page\.auctions\.yahoo\.co\.jp/[^"]+)"', item)
            id_m = re.search(r'auction/([a-zA-Z0-9]+)', item)

            if not (title_m and link_m):
                continue

            item_id = id_m.group(1) if id_m else link_m.group(1)[-20:]
            price = f"¥{price_m.group(1)}" if price_m else "N/A"

            results.append({
                "id": f"yahoo_{item_id}",
                "title": title_m.group(1).strip(),
                "price": price,
                "url": link_m.group(1),
                "platform": "Yahoo Auctions JP",
            })
    except Exception as e:
        log.warning(f"Yahoo JP scrape error ({keyword}): {e}")
    return results

# ── TCGPlayer scraper ─────────────────────────────────────────────────────────

async def scrape_tcgplayer(session: aiohttp.ClientSession, keyword: str) -> list:
    results = []
    url = f"https://www.tcgplayer.com/search/one-piece-card-game/product?q={keyword.replace(' ', '+')}&view=grid"
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return results
            html = await resp.text()

        items = re.findall(r'class="search-result".*?(?=class="search-result"|$)', html, re.DOTALL)
        for item in items[:10]:
            title_m = re.search(r'class="search-result__title"[^>]*>([^<]+)', item)
            price_m = re.search(r'class="search-result__market-price[^"]*"[^>]*>.*?\$([\d.]+)', item, re.DOTALL)
            link_m = re.search(r'href="(/product/[^"]+)"', item)

            if not (title_m and link_m):
                continue

            results.append({
                "id": f"tcp_{abs(hash(link_m.group(1)))}",
                "title": title_m.group(1).strip(),
                "price": f"${price_m.group(1)}" if price_m else "N/A",
                "url": f"https://www.tcgplayer.com{link_m.group(1)}",
                "platform": "TCGPlayer",
            })
    except Exception as e:
        log.warning(f"TCGPlayer scrape error ({keyword}): {e}")
    return results

# ── Good Games AU scraper ─────────────────────────────────────────────────────

async def scrape_goodgames(session: aiohttp.ClientSession, keyword: str) -> list:
    results = []
    url = f"https://goodgames.com.au/search?type=product&q={keyword.replace(' ', '+')}"
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return results
            html = await resp.text()

        items = re.findall(r'class="product-item[^"]*".*?(?=class="product-item|$)', html, re.DOTALL)
        for item in items[:10]:
            title_m = re.search(r'class="product-item__title[^"]*"[^>]*>([^<]+)', item)
            price_m = re.search(r'class="price[^"]*"[^>]*>.*?\$([\d.]+)', item, re.DOTALL)
            link_m = re.search(r'href="(/products/[^"]+)"', item)

            if not (title_m and link_m):
                continue

            results.append({
                "id": f"gg_{abs(hash(link_m.group(1)))}",
                "title": title_m.group(1).strip(),
                "price": f"A${price_m.group(1)}" if price_m else "N/A",
                "url": f"https://goodgames.com.au{link_m.group(1)}",
                "platform": "Good Games AU",
            })
    except Exception as e:
        log.warning(f"Good Games scrape error ({keyword}): {e}")
    return results

# ── Filter ────────────────────────────────────────────────────────────────────

PROMO_SIGNALS = [
    "promo", "prize", "winner", "finalist", "regional", "championship",
    "tournament", "pre-release", "prerelease", "treasure cup", "store champion",
    "worlds", "bandai fest", "serial", "numbered", "プロモ", "優勝", "賞品",
    "大会", "予選", "店舗大会", "プレリリース",
]

def is_relevant(title: str) -> bool:
    title_lower = title.lower()
    if "one piece" not in title_lower and "ワンピース" not in title:
        return False
    return any(sig in title_lower for sig in PROMO_SIGNALS)

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log.info("🏴‍☠️ One Piece Low Pop Bot — GitHub Actions run starting")

    seen = load_seen()
    new_seen = set()
    alerts_sent = 0

    async with aiohttp.ClientSession() as session:
        # Test Discord connectivity first
        test_payload = {
            "content": None,
            "embeds": [{
                "title": "🏴‍☠️ OP Bot scan started",
                "description": f"Scanning {len(KEYWORDS)} EN + {len(JP_KEYWORDS)} JP keywords across eBay, Yahoo Auctions JP, TCGPlayer, Good Games AU",
                "color": 0x2ECC71,
                "footer": {"text": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
            }]
        }
        async with session.post(DISCORD_WEBHOOK, json=test_payload) as resp:
            if resp.status in (200, 204):
                log.info("✅ Discord webhook working")
            else:
                text = await resp.text()
                log.error(f"❌ Discord webhook FAILED: {resp.status} — {text}")
                return

        all_listings = []

        # EN keywords → eBay + TCGPlayer + Good Games
        for kw in KEYWORDS:
            log.info(f"Scanning EN: {kw}")
            all_listings += await scrape_ebay(session, kw)
            all_listings += await scrape_tcgplayer(session, kw)
            all_listings += await scrape_goodgames(session, kw)
            await asyncio.sleep(1)

        # JP keywords → Yahoo Auctions
        for kw in JP_KEYWORDS:
            log.info(f"Scanning JP: {kw}")
            all_listings += await scrape_yahoo_jp(session, kw)
            await asyncio.sleep(1)

        log.info(f"Found {len(all_listings)} raw listings — filtering...")

        for listing in all_listings:
            if not is_relevant(listing["title"]):
                continue
            if listing["id"] in seen:
                continue

            new_seen.add(listing["id"])
            await send_discord(session, listing)
            alerts_sent += 1
            await asyncio.sleep(0.5)

        # Summary
        summary_payload = {
            "embeds": [{
                "title": "✅ Scan complete",
                "description": f"Sent **{alerts_sent}** new alerts from {len(all_listings)} listings checked.",
                "color": 0x3498DB,
                "footer": {"text": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
            }]
        }
        async with session.post(DISCORD_WEBHOOK, json=summary_payload) as resp:
            pass

    # Save seen IDs
    save_seen(seen | new_seen)
    log.info(f"Done. {alerts_sent} alerts sent, {len(new_seen)} new IDs saved.")

if __name__ == "__main__":
    asyncio.run(main())
