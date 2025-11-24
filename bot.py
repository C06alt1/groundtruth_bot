import feedparser
from PyPDF2 import PdfReader
import pandas as pd
from bs4 import BeautifulSoup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
import time
import threading
from datetime import datetime, time as dt_time
import hashlib
import requests
import asyncio
import re  # For escaping
import random
import os
from io import BytesIO
import logging

# === CONFIG ===
TOKEN = os.getenv('RENDER_BOT_TOKEN', '8588832961:AAFF9IELLtd6CEt24uL1nhh3kjEIactAQNs')
GROQ_KEY = os.getenv('GROQ_API_KEY')
YOUR_CHAT_ID = 5554592254  # ← CHANGE TO YOUR REAL TELEGRAM ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache processed files
CACHE_FILE = "/tmp/processed.txt"
PROCESSED = set()
if os.path.exists(CACHE_FILE):
    PROCESSED = set(open(CACHE_FILE).read().splitlines())

def save_cache():
    open(CACHE_FILE, "w").write("\n".join(PROCESSED))

# Pages to crawl
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
    logger.info(f"Loaded {len(PAGES)} sources from {SOURCES_FILE}")
else:
    logger.warning(f"{SOURCES_FILE} not found — using fallback pages")
    PAGES = [
        "rss:https://hackaday.com/feed/",
        "rss:https://www.therobotreport.com/feed/",
        "rss:https://robots.net/feed/"
    ]

def get_latest_file(page_url):
    try:
        r = requests.get(page_url, timeout=20)
        soup = BeautifulSoup(r.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if any(ext in href for ext in ['.csv', '.xlsx', '.xls', '.pdf', '.html']):
                return requests.compat.urljoin(page_url, a['href'])
    except:
        pass
    return None

async def process_rss_feed(feed_url, context, chat_id):
    """Parses an RSS feed and processes new entries."""
    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo:
            logger.warning(f"Error parsing RSS feed {feed_url}: {feed.bozo_exception}")
            return 0

        count = 0
        for entry in feed.entries:
            entry_id = entry.get('id', entry.link)
            if entry_id in PROCESSED:
                continue

            # We have a new entry, process it
            try:
                # Prioritize content from the feed entry itself
                text = ""
                if 'content' in entry:
                    soup = BeautifulSoup(entry.content[0].value, 'html.parser')
                    text = soup.get_text(separator="\n")
                elif 'summary' in entry:
                    soup = BeautifulSoup(entry.summary, 'html.parser')
                    text = soup.get_text(separator="\n")

                # If feed did not contain content, fall back to fetching the link
                if not text or len(text) < 200:
                    data = requests.get(entry.link, timeout=30).content
                    file_name = entry.link.split("/")[-1] or "article.html"
                    text = extract_text(data, file_name)

                if not text or len(text) < 100:
                    logger.warning(f"Could not extract sufficient text from {entry.link}")
                    continue

                # Generate article and image
                title, article_text = await make_article(text, entry.link)
                
                if "|" not in title and len(title) > 40:
                    words = title.split()
                    title = " | ".join([" ".join(words[i:i+4]) for i in range(0, len(words), 4)])

                image_bytesio = generate_image_from_title(title.replace("|", " "))

                await send_reuters_style(
                    bot=context.bot,
                    chat_id=chat_id,
                    title=title,
                    article_text=article_text,
                    source_url=entry.link,
                    image_bytesio=image_bytesio
                )

                PROCESSED.add(entry_id)
                save_cache()
                count += 1

            except Exception as e:
                logger.error(f"Error processing RSS entry {entry.link}: {e}")
        
        return count
    except Exception as e:
        logger.error(f"Failed to process RSS feed {feed_url}: {e}")
        return 0
        
async def run_scan(context, chat_id):
    total_new_articles = 0
    for page in PAGES:
        if page.startswith("rss:"):
            feed_url = page.replace("rss:", "").strip()
            total_new_articles += await process_rss_feed(feed_url, context, chat_id)
        else:
            file_url = get_latest_file(page)
            if not file_url:
                continue
            try:
                data = requests.get(file_url, timeout=30).content
                file_hash = hashlib.sha256(data).hexdigest()
                if file_hash in PROCESSED:
                    continue

                text = extract_text(data, file_url.split("/")[-1])

                title, article_text = await make_article(text, file_url)

                if "|" not in title and len(title) > 40:
                    words = title.split()
                    title = " | ".join([" ".join(words[i:i+4]) for i in range(0, len(words), 4)])

                image_bytesio = generate_image_from_title(title.replace("|", " "))

                await send_reuters_style(
                    bot=context.bot,
                    chat_id=chat_id,
                    title=title,
                    article_text=article_text,
                    source_url=file_url,
                    image_bytesio=image_bytesio
                )

                PROCESSED.add(file_hash)
                save_cache()
                total_new_articles += 1
            except Exception as e:
                logger.error(f"Error processing file {file_url}: {e}")

    await context.bot.send_message(chat_id, f"Scan complete — {total_new_articles} new article(s) found.")

def extract_text(data, name):
    name = name.lower()
    try:
        if name.endswith('.csv'):
            return pd.read_csv(BytesIO(data)).head(60).to_string()
        if name.endswith(('.xls', '.xlsx')):
            return pd.read_excel(BytesIO(data)).head(40).to_string()
        if name.endswith('.pdf'):
            reader = PdfReader(BytesIO(data))
            return "\n".join(
                (p.extract_text() or "")[:2000]
                for p in reader.pages[:10]
            )
        if name.endswith(('.html', '.htm')):
            soup = BeautifulSoup(data.decode("utf-8", errors="ignore"), "html.parser")
            text = soup.get_text(separator="\n")
            return text[:5000]
    except Exception as e:
        return f"Error reading file: {e}"
    return "Could not read file"

def generate_text(prompt: str,
                  model: str = "llama-3.3-70b-versatile",
                  max_tokens: int = 200,
                  temperature: float = 0.9) -> str:
    if not GROQ_KEY:
        return "Error: GROQ API key not set."
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            timeout=40
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        return text
    except Exception as e:
        logger.error(f"Groq text generation failed: {e}", exc_info=True)
        return f"Error during text generation: {e}"

async def make_article(text: str, url: str):
    if not GROQ_KEY:
        return "Data Update", "GROQ API key missing"
    title_payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": 
             "You are a Reuters headline writer.\n"
             "Return ONLY the headline. No quotes, no extra text.\n"
             "Examples:\n"
             "EXCLUSIVE : Actor James Dead dead in car crash age 32\n"
             "BREAKING : Major earthquake hits city | Thousands displaced | Aid efforts underway\n"
             "TOP NEWS : Global markets rally | Oil prices surge | Tech stocks lead gains\n"},
            {"role": "user", "content": f"Source: {url}\nData:\n{text[:5000]}"}
        ],
        "temperature": 0.15,
        "max_tokens": 80
    }
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=title_payload,
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            timeout=45
        )
        resp.raise_for_status()
        raw_title = resp.json()["choices"][0]["message"]["content"].strip()
        title = raw_title.replace('"', '').replace("'", "").strip()
        if not title:
            title = "Data Update"
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        title = "Data Update"
    article_payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": 
             "Write a summary in exactly two paragraphs. Each paragraph must contain about 80 words, with a single clear line break between paragraphs. "
             "Speak in the witty style of Jeremy Clarkson."},
            {"role": "user", "content": f"Source: {url}\nData:\n{text[:14000]}"}
        ],
        "temperature": 0.9,
        "max_tokens": 350
    }
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=article_payload,
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            timeout=60
        )
        resp.raise_for_status()
        article_text = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Article generation failed: {e}")
        article_text = "Summary unavailable."
    return title, article_text

def generate_image_from_title(title: str):
    try:
        account_id = os.getenv("CF_ACCOUNT_ID","f5057d0d7c5d703abff6a8ce24a499dd")
        api_token = os.getenv("CF_API_TOKEN","x8OoUEnhDvA-0_FLfcWbsXdgaRrXPBKE0BcV8Zmy")
        if not account_id or not api_token:
            raise ValueError("CF_ACCOUNT_ID or CF_API_TOKEN is missing")

        API_BASE_URL = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/"
        model = "@cf/stabilityai/stable-diffusion-xl-base-1.0"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "prompt": title,
            "size": "1280x720",
            "steps": 25,
            "cfg_scale": 7.0,
            "samples": 1
        }
        logger.info(f"[DEBUG] Sending prompt to Workers AI: {title}")
        resp = requests.post(f"{API_BASE_URL}{model}", headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        img_bytes = resp.content
        
        if not img_bytes:
            logger.error(f"No image data returned: {resp.text}")
            return None

        logger.info(f"[DEBUG] Image generated successfully")
        return BytesIO(img_bytes)
    except Exception as e:
        logger.error(f"Cloudflare Workers AI image generation failed: {e}", exc_info=True)
        return None

async def post_init(application: Application):
    """Runs once on startup."""
    job_queue = application.job_queue
    job_queue.run_once(generate_story, 0)

async def generate_story(context: ContextTypes.DEFAULT_TYPE):
    application = context.application
    test_text = generate_text("Tell a random slightly surreal story that is related to a news story of the day as if its true",
                        temperature=0.7)
    
    logger.info(test_text)
    test_url = "https://groundtruth.com"
    title, article_text = await make_article(test_text, test_url)
    logger.info(f"Generated test title: {title}")
    logger.info(f"Generated test article: {article_text}")
    image_bytesio = generate_image_from_title(title.replace("|", " "))
    await send_reuters_style(
        bot=application.bot,
        chat_id=YOUR_CHAT_ID,
        title=title,
        article_text=article_text,
        source_url=test_url,
        image_bytesio=image_bytesio,
    )

async def send_reuters_style(bot, chat_id, title: str, article_text: str, source_url: str, image_bytesio=None):
    formatted_title = f"*{title}*"
    read_more_text = f"\n\n[read more]({source_url})"
    max_len = 1024
    available_len = max_len - len(formatted_title) - len(read_more_text)
    if len(article_text) > available_len:
        article_text = article_text[:available_len - 3] + "..."
    caption = f"{formatted_title}\n\n{article_text}{read_more_text}"
    if image_bytesio:
        image_bytesio.name = "news.jpg"
        image_bytesio.seek(0)
        await bot.send_photo(
            chat_id=chat_id,
            photo=image_bytesio,
            caption=caption,
            parse_mode='Markdown',
            disable_notification=True
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode='Markdown',
            disable_web_page_preview=True,
            disable_notification=True
        )

async def manual_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Starting scan…")
    await run_scan(context, update.effective_chat.id)

def main():
    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    job_queue = application.job_queue
    job_queue.run_repeating(generate_story, interval=3600)
    application.add_handler(CommandHandler("scan", manual_scan))
    logger.info("GroundTruth bot started")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
