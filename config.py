"""
One Piece TCG Low Pop Bot — Configuration
Edit this file to change keywords, thresholds, and API keys.
"""

CONFIG = {

    # ── Discord ──────────────────────────────────────────────
    "discord_webhook": "https://discord.com/api/webhooks/1486315097898090556/UR0n6IJStodJp_v-cHYq1rzU0etxnkzx5tQS5h_qdCd1YZ9sVLdRUbDaN4oXxjF-3ZvP",

    # ── eBay ─────────────────────────────────────────────────
    # Paste your eBay App ID (client ID) from developer.ebay.com
    # Leave as None to use the HTML scrape fallback (slower but no key needed)
    "ebay_app_id": None,  # e.g. "YourName-AppName-PRD-abc123-def456"

    # ── Pop filter ───────────────────────────────────────────
    # Alert when PSA 10 population is BELOW this number
    # Set to None to alert on everything regardless of pop
    "pop_threshold": 10000,

    # Set to False to skip pop checking (faster scans, more alerts)
    "check_pop": True,

    # ── Scan frequency ───────────────────────────────────────
    "scan_interval_minutes": 30,

    # ── Search keywords ──────────────────────────────────────
    # These are combined with "one piece" and searched across all platforms
    # Add or remove as needed
    "keywords": [
        "promo",
        "prize",
        "winner",
        "finalist",
        "regional",
        "championship",
        "tournament winner",
        "pre-release",
        "treasure cup",
        "store champion",
        "worlds",
        "bandai fest",
    ],

    # ── Japanese keywords for Yahoo Auctions ─────────────────
    "jp_keywords": [
        "ワンピース プロモ",       # One Piece promo
        "ワンピース 優勝",         # One Piece winner
        "ワンピース 大会 賞品",    # One Piece tournament prize
        "ワンピース 地区予選",     # One Piece regional qualifier
        "ワンピース 決勝",         # One Piece finals
        "ワンピース 店舗大会",     # One Piece store tournament
        "ワンピース プレリリース",  # One Piece pre-release
    ],

    # ── Browser user agent ───────────────────────────────────
    "user_agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}
