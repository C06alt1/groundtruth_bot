import logging, os, requests, hashlib
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from bs4 import BeautifulSoup
import pandas as pd
from io import BytesIO
from PyPDF2 import PdfReader

# === CONFIG ===
TOKEN = os.getenv('RENDER_BOT_TOKEN')
DEEPSEEK_KEY = os.getenv('DEEPSEEK_API_KEY')
YOUR_CHAT_ID = 5554592254  # ← CHANGE TO YOUR TELEGRAM ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache: remember which files we already processed
CACHE_FILE = "/tmp/processed.txt"
PROCESSED = set(open(CACHE_FILE).read().splitlines() if os.path.exists(CACHE_FILE) else [])
def save(): open(CACHE_FILE, "w").write("\n".join(PROCESSED))

# Pages to crawl
PAGES = [
    "https://www.ons.gov.uk/peoplepopulationandcommunity/birthsdeathsandmarriages/deaths/datasets/weeklyprovisionalfiguresondeathsregisteredinenglandandwales",
    "https://data.cdc.gov/NCHS/Provisional-COVID-19-Death-Counts-by-Week-Ending-D/r8kw-7aab",
    "https://www.who.int/data/collections/excess-mortality",
    "https://vaers.hhs.gov/data/datasets.html",
    "https://www.ecdc.europa.eu/en/publications-data/weekly-respiratory-illnesses-surveillance-summary-europe",
]

# Find first CSV/Excel/PDF link on a page
def get_latest_file(page_url):
    try:
        soup = BeautifulSoup(requests.get(page_url, timeout=20).text, 'html.parser')
        for a in soup.find_all('a', href=True):
            h = a['href'].lower()
            if any(x in h for x in ['.csv','.xlsx','.xls','.pdf']):
                return requests.compat.urljoin(page_url, a['href'])
    except: pass
    return None

# Extract text from file
def extract_text(data, name):
    name = name.lower()
    try:
        if name.endswith('.csv'): return pd.read_csv(BytesIO(data)).head(60).to_string()
        if name.endswith(('.xls','.xlsx')): return pd.read_excel(BytesIO(data)).head(40).to_string()
        if name.endswith('.pdf'):
            r = PdfReader(BytesIO(data))
            return "\n".join(p.extract_text()[:2000] for p in r.pages[:10])
    except: pass
    return "Could not read file"

# Call DeepSeek API
async def make_article(text, url):
    if not DEEPSEEK_KEY: return "No DEEPSEEK_API_KEY"
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "PureFact Writer. Use ONLY data. Cite every number."},
            {"role": "user", "content": f"URL: {url}\nData:\n{text[:14000]}"}
        ],
        "temperature": 0.1, "max_tokens": 1800
    }
    try:
        r = requests.post("https://api.deepseek.com/v1/chat/completions", json=payload,
                          headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"}, timeout=90)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"API error: {e}"

# One scan
async def run_scan(context, chat_id):
    count = 0
    for page in PAGES:
        file_url = get_latest_file(page)
        if not file_url: continue
        try:
            data = requests.get(file_url, timeout=30).content
            h = hashlib.sha256(data).hexdigest()
            if h in PROCESSED: continue

            text = extract_text(data, file_url.split("/")[-1])
            article = await make_article(text, file_url)
            full = f"PureFact Article – {datetime.now():%Y-%m-%d}\nSource: {file_url}\n\n{article}"
            for part in [full[i:i+4000] for i in range(0, len(full), 4000)]:
                await context.bot.send_message(chat_id, part, disable_web_page_preview=True)

            PROCESSED.add(h)
            save()
            count += 1
        except Exception as e:
            logger.error(f"{file_url}: {e}")
    await context.bot.send_message(chat_id, f"Done — {count} new article(s)")

# Commands
async def daily(context): await run_scan(context, context.job.chat_id)
async def manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scanning…")
    await run_scan(context, update.effective_chat.id)

# Render port fix
if os.getenv('RENDER'):
    from flask import Flask
    from waitress import serve
    import threading
    app = Flask(__name__)
    @app.route("/"); def _(): return "alive", 200
    threading.Thread(target=serve, args=(app,), kwargs={"host":"0.0.0.0","port":int(os.environ.get("PORT",8000))}, daemon=True).start()

# Start bot
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("scan", manual))
    app.job_queue.run_daily(daily, time=datetime.utcnow().replace(hour=8, minute=0, second=0), chat_id=YOUR_CHAT_ID)
    app.run_polling()

if __name__ == '__main__':
    main()
