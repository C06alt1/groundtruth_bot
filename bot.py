import logging
import os
import requests
import pandas as pd
from io import BytesIO
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from datetime import datetime, timedelta
import hashlib
from PyPDF2 import PdfReader

TOKEN = os.getenv('RENDER_BOT_TOKEN', '8588832961:AAFF9IELLtd6CEt24uL1nhh3kjEIactAQNs')  # Replace if not using env
DEEPSEEK_KEY = os.getenv('DEEPSEEK_API_KEY' , 'sk-1935e7fc00a347b5a1a9797c8bff49f2')
SOURCES_URL = "https://raw.githubusercontent.com/C06alt1/purefact-bot/main/sources.txt"  # ← CHANGE YOURNAME

# Replace YOURNAME above with your actual GitHub username

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Remember which files we already processed (simple in-memory + file on disk)
PROCESSED_CACHE = set()
CACHE_FILE = "/tmp/processed_cache.txt"
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        PROCESSED_CACHE.update(f.read().splitlines())

def save_cache():
    with open(CACHE_FILE, "w") as f:
        f.write("\n".join(PROCESSED_CACHE))

async def daily_scan(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=context.job.chat_id, text="Starting daily PureFact scan…")
    count = await run_full_scan(context)
    await context.bot.send_message(chat_id=context.job.chat_id, text=f"Scan complete — {count} new article(s) generated.")

async def manual_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Manual scan started…")
    count = await run_full_scan(context, chat_id=update.effective_chat.id)
    await update.message.reply_text(f"Done — {count} new article(s).")

async def run_full_scan(context, chat_id=None):
    sources = requests.get(SOURCES_URL).text.strip().splitlines()
    sources = [s.strip() for s in sources if s.strip() and not s.startswith("#")]
    new_count = 0

    for url in sources:
        try:
            article = await process_url(url)
            if article:
                target = chat_id or context.job.chat_id
                for chunk in [article[i:i+4000] for i in range(0, len(article), 4000)]:
                    await context.bot.send_message(chat_id=target, text=chunk, disable_web_page_preview=True)
                new_count += 1
        except Exception as e:
            logger.error(f"Error with {url}: {e}")

    save_cache()
    return new_count

async def process_url(url: str):
    headers = {'User-Agent': 'PureFactBot/1.0'}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    content = r.content
    file_hash = hashlib.sha256(content).hexdigest()
    if file_hash in PROCESSED_CACHE:
        return None  # already done

    filename = url.split("/")[-1] or "datafile"
    raw_text = extract_text(content, filename)

    article = await generate_article(raw_text, url)
    PROCESSED_CACHE.add(file_hash)
    return f"PureFact Article – {datetime.now():%Y-%m-%d}\nTopic: {filename}\n\n{article}\n\nSource: {url}"

def extract_text(data: bytes, name: str) -> str:
    name = name.lower()
    try:
        if name.endswith(('.csv', '.tsv')):
            return pd.read_csv(BytesIO(data)).head(60).to_string()
        if name.endswith(('.xls', '.xlsx')):
            xl = pd.ExcelFile(BytesIO(data))
            return " | ".join(xl.sheet_names) + "\n" + pd.read_excel(BytesIO(data)).head(40).to_string()
        if name.endswith('.pdf'):
            reader = PdfReader(BytesIO(data))
            return "\n".join(page.extract_text()[:3000] for page in reader.pages[:10])
        if name.endswith('.json'):
            return str(requests.get(url).json())[:15000]
        return str(data[:15000])
    except:
        return str(data[:15000])

async def generate_article(raw: str, source_url: str) -> str:
    if not DEEPSEEK_KEY:
        return "DEEPSEEK_API_KEY missing"

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are PureFact Article Writer. Use ONLY the raw data below. Every number/claim ends with [Source: row/sheet/link]. Zero opinion."},
            {"role": "user", "content": f"Source URL: {source_url}\n\nRaw data (first chunk):\n{raw[:14000]}"}
        ],
        "temperature": 0.1,
        "max_tokens": 1800
    }
    try:
        r = requests.post("https://api.deepseek.com/v1/chat/completions", json=payload,
                          headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"}, timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Generation failed: {e}"

# === RENDER PORT FIX (still included) ===
# === RENDER PORT FIX – keeps Render happy without affecting the bot ===
if os.getenv('RENDER'):
    from flask import Flask
    from waitress import serve
    import threading

    flask_app = Flask(__name__)

    @flask_app.route("/")
    def home():
        return "PureFact bot alive", 200

    def run_web_server():
        serve(flask_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

    threading.Thread(target=run_web_server, daemon=True).start()
# =====================================================================
def main():
    if not TOKEN: return logger.error("No token")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text("PureFact Daily Scanner ready\nUse /scan for manual run")))
    app.add_handler(CommandHandler("scan", manual_scan))

    # Daily auto-scan at 08:00 UTC (adjust if you want)
    job_queue = app.job_queue
    job_queue.run_daily(daily_scan, time=datetime.utcnow().replace(hour=15, minute=0, second=0, microsecond=0), chat_id=5554592254)

    logger.info("PureFact Daily Scanner started")
    app.run_polling()

if __name__ == '__main__':
    main()
