# One Piece Low Pop Alert Bot — Setup Guide

## What it does
Scans eBay (BIN + auctions), Yahoo Auctions Japan, TCGPlayer,
Good Games AU, and Eternal Games every 30 minutes. When it finds
a promo/prize/winner card with PSA 10 pop below your threshold,
it sends a Discord alert with the price and a direct buy link.

---

## Option A — Deploy to Railway (FREE, runs 24/7, recommended)

Railway gives you 500 free hours/month — enough to run this bot
continuously at no cost.

### Step 1 — Upload to GitHub
1. Go to github.com → click "+" → "New repository"
2. Name it `op-low-pop-bot`, make it Private, click Create
3. On your computer, open Terminal (Mac) or Command Prompt (Windows)
4. Run these commands one by one:
```
cd path/to/op-bot-folder
git init
git add .
git commit -m "initial"
git remote add origin https://github.com/YOUR_USERNAME/op-low-pop-bot.git
git push -u origin main
```

### Step 2 — Deploy on Railway
1. Go to railway.app → sign up with GitHub (free)
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your `op-low-pop-bot` repo
4. Railway auto-detects Python and deploys — done!

### Step 3 — Check it's running
- Click your project in Railway → "View Logs"
- You should see: `🏴‍☠️ One Piece Low Pop Bot starting...`
- Check your Discord — a startup message should arrive within 1 minute

---

## Option B — Run locally on your computer

### Requirements
- Python 3.11+ installed (python.org)

### Install and run
```bash
cd op-bot
pip install -r requirements.txt
python bot.py
```

**Note:** Your computer must stay on and connected for alerts to work.
Use Railway (Option A) for 24/7 monitoring.

---

## Configuration (config.py)

| Setting | Default | Description |
|---|---|---|
| `pop_threshold` | 100 | Alert when PSA 10 pop is below this |
| `check_pop` | True | Look up pop on PriceCharting before alerting |
| `scan_interval_minutes` | 30 | How often to scan (min 15 recommended) |
| `keywords` | see file | Search terms used across all platforms |
| `ebay_app_id` | None | Paste your eBay App ID for better results |

### Adding your eBay App ID (optional but recommended)
1. Go to developer.ebay.com → sign in
2. My Account → Application Keys → Production → copy "App ID (Client ID)"
3. Paste it in config.py: `"ebay_app_id": "YourApp-Name-PRD-abc123"`
4. Redeploy (push to GitHub → Railway auto-redeploys)

---

## Customising keywords

Edit `config.py` to add/remove keywords. For example to also watch
for specific characters:
```python
"keywords": [
    "promo",
    "winner",
    "finalist",
    "regional",
    "luffy winner",      # add specific cards
    "ace promo",
    "zoro prize",
],
```

---

## What a Discord alert looks like

```
🚨 One Piece TCG Regional Finalist Promo Luffy 2024
💰 Price: USD 89.99
📊 PSA 10 pop: 7
🏪 Platform: eBay — Buy It Now
[direct link to listing]
```

---

## Troubleshooting

**No alerts arriving:**
- Check Railway logs for errors
- Your keywords might be too specific — try broader terms
- Pop checker might be filtering too aggressively — set `check_pop: False` temporarily

**Too many alerts:**
- Lower `pop_threshold` (e.g. to 20 or 10)
- Make keywords more specific

**Bot crashed:**
- Railway auto-restarts on failure
- Check logs for the error message
