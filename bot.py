### Quick Fixed Version
Here's the **corrected full `bot.py`** (copy-paste this over your current file and commit). I fixed the syntax, model, and minor nits—test with `/scan` after deploy.

```python
import logging
import os
import requests
import hashlib
from datetime import datetime
import threading
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from bs4 import BeautifulSoup
import pandas as pd
from io import BytesIO
from PyPDF2 import PdfReader

# === CONFIG ===
TOKEN = os.getenv('RENDER_BOT_TOKEN')
GROQ_KEY = os.getenv('GROQ_API_KEY')  # Free: https://console.groq.com/keys
YOUR_CHAT_ID = 123456789  # ← CHANGE TO YOUR REAL TELEGRAM ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache processed files
CACHE_FILE = "/tmp/processed.txt"
PROCESSED = set()
if os.path.exists(CACHE_FILE):
 PROCESSED = set(open(CACHE_FILE).read().splitlines())

def save_cache():
 open(CACHE_FILE, "w").write("\n".join(PROCESSED))

# Pages to crawl (from sources.txt or hard-coded fallback)
PAGES = []
SOURCES_FILE = "sources.txt"
if os.path.exists(SOURCES_FILE):
 with open(SOURCES_FILE) as f:
     raw_lines = f.readlines()
 PAGES = [
     line.strip()
     for line in raw_lines
     if line.strip() and not line.startswith("#")
 ]
 logger.info(f"Loaded {len(PAGES)} sources from sources.txt")
else:
 logger.warning("sources.txt not found — using fallback pages")
 PAGES = [
     "https://www.ons.gov.uk/peoplepopulationandcommunity/birthsdeathsandmarriages/deaths/datasets/weeklyprovisionalfiguresondeathsregisteredinenglandandwales",
     "https://data.cdc.gov/NCHS/Provisional-COVID-19-Death-Counts-by-Week-Ending-D/r8kw-7aab",
     "https://www.who.int/data/collections/excess-mortality",
     "https://vaers.hhs.gov/data/datasets.html",
     "https://www.ecdc.europa.eu/en/publications-data/weekly-respiratory-illnesses-surveillance-summary-europe",
 ]

def get_latest_file(page_url):
 try:
     r = requests.get(page_url, timeout=20)
     soup = BeautifulSoup(r.text, 'html.parser')
     for a in soup.find_all('a', href=True):
         href = a['href'].lower()
         if any(ext in href for ext in ['.csv', '.xlsx', '.xls', '.pdf']):
             return requests.compat.urljoin(page_url, a['href'])
 except:
     pass
 return None

def extract_text(data, name):
 name = name.lower()
 try:
     if name.endswith('.csv'):
         return pd.read_csv(BytesIO(data)).head(60).to_string()
     if name.endswith(('.xls', '.xlsx')):
         return pd.read_excel(BytesIO(data)).head(40).to_string()
     if name.endswith('.pdf'):
         reader = PdfReader(BytesIO(data))
         return "\n".join(p.extract_text()[:2000] for p in reader.pages[:10])
 except:
     pass
 return "Could not read file"

async def make_article(text, url):
 if not GROQ_KEY:
     return "GROQ_API_KEY missing — get free key at https://console.groq.com/keys"
 payload = {
     "model": "llama-3.3-70b-versatile",  # Fixed: Active model (no 400s)
     "messages": [
         {"role": "system", "content": "You are PureFact Writer. Use ONLY the data. Cite every number. Zero opinion."},
         {"role": "user", "content": f"Source: {url}\nData:\n{text[:14000]}"}
     ],
     "temperature": 0.1,
     "max_tokens": 1800
 }
 try:
     r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                       json=payload,
                       headers={"Authorization": f"Bearer {GROQ_KEY}"},
                       timeout=60)
     r.raise_for_status()
     return r.json()["choices"][0]["message"]["content"]
 except Exception as e:
     return f"API error: {e}"

async def run_scan(context, chat_id):
 count = 0
 for page in PAGES:
     file_url = get_latest_file(page)
     if not file_url: continue
     try:
         data = requests.get(file_url, timeout=30).content
         file_hash = hashlib.sha256(data).hexdigest()
         if file_hash in PROCESSED: continue

         text = extract_text(data, file_url.split("/")[-1])
         article = await make_article(text, file_url)
         full_msg = f"PureFact Article – {datetime.now():%Y-%m-%d}\nSource: {file_url}\n\n{article}"

         for part in [full_msg[i:i+4000] for i in range(0, len(full_msg), 4000)]:
             await context.bot.send_message(chat_id, part, disable_web_page_preview=True)

         PROCESSED.add(file_hash)
         save_cache()
         count += 1
     except Exception as e:
         logger.error(f"Error {file_url}: {e}")

 await context.bot.send_message(chat_id, f"Scan complete — {count} new article(s)")

async def daily_scan(context):
 await run_scan(context, context.job.chat_id)

async def manual_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
 await update.message.reply_text("Starting scan…")
 await run_scan(context, update.effective_chat.id)

# === RENDER FREE-TIER FIX: port 80 + Google ping every 30s ===
if os.getenv('RENDER'):
 from flask import Flask

 app = Flask(__name__)

 @app.route("/")
 def health():
     return "PureFact bot alive and healthy", 200

 # Google ping every 30 seconds
 def google_ping():
     while True:
         try:
             requests.get("https://www.google.com", timeout=10)
         except: pass
         time.sleep(30)

 # Start Flask on port 80 + pinger
 threading.Thread(target=lambda: app.run(host="0.0.0.0", port=80), daemon=True).start()
 threading.Thread(target=google_ping, daemon=True).start()
# ===============================================================

def main():
 if not TOKEN:
     logger.error("No TOKEN")
     return

 application = Application.builder().token(TOKEN).build()
 application.add_handler(CommandHandler("scan", manual_scan))
 application.job_queue.run_daily(
     daily_scan,
     time=datetime.now().replace(hour=8, minute=0, second=0, microsecond=0),
     chat_id=YOUR_CHAT_ID
 )
 logger.info("PureFact bot started")
 application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
 main()
