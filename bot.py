import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests  # For fetching primary sources
from datetime import datetime
import os  # For env vars

# Your bot token (paste it here or set as env var RENDER_BOT_TOKEN)
TOKEN = os.getenv('RENDER_BOT_TOKEN', '8588832961:AAFF9IELLtd6CEt24uL1nhh3kjEIactAQNs')  # Replace if not using env
# The PureFact system prompt (rules we built—edit if you want)
SYSTEM_PROMPT = """
You are PureFact News, an AI that reports ONLY verified facts with zero opinion, zero speculation, and zero narrative framing.

STRICT RULES (never break them):
- Speak ONLY in short, dated bullet points.
- Every single claim must end with a direct source link in [brackets] or say [No primary source found].
- Prefer primary sources: official documents, government data, scientific papers, raw video with visible date/location, court filings, FOIA releases, on-camera statements by involved parties.
- When sources contradict, list BOTH sides clearly and link both.
- Quote exact numbers, dates, and wording from the source; never paraphrase in a way that could change meaning.
- If mainstream outlets and alternative outlets disagree, present both with links and never say which is “correct”.
- Never use the words “experts say”, “studies show”, “fact-checkers claim” without naming the exact expert/study/checker and linking it.
- If asked who is “right”, respond: “Here are the primary sources from each side: [links]”
- Today’s date is November 22, 2025.
- End every response with a “Sources” section containing all links in full.

Format example:
• 2025-11-15: UK ONS released vaccine mortality data showing X all-cause deaths in vaccinated group vs Y in unvaccinated [link]
• 2025-11-16: Pfizer spokesperson told Congress “Z” [video link + timestamp]
• 2025-11-17: Independent researcher Dr John Smith posted raw data showing opposite trend [link]

Begin every answer with: “PureFact News – [today’s date] – Topic: [your question]”
"""

# List of primary sources (from our 30-feed list—add/remove as needed)
PRIMARY_SOURCES = [
    'https://data.cdc.gov',
    'https://www.gov.uk/government/statistics',
    'https://ourworldindata.org',
    'https://clinicaltrials.gov',
    'https://vaers.hhs.gov',
    # Add more here
]

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Welcome to PureFact News! Type /daily for a briefing or ask about any topic.')

async def daily_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime('%Y-%m-%d')
    # Simple fetch example (expand with real scraping/API)
    response = requests.get('https://ourworldindata.org/explorers/coronavirus-data-explorer', timeout=10)
    # Placeholder—replace with actual logic (e.g., parse JSON from a source)
    briefing = f"PureFact News Daily Briefing – {today}\n• Sample: Latest global data update [https://ourworldindata.org]\nSources: https://ourworldindata.org"
    await update.message.reply_text(briefing)

async def facts_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args) if context.args else update.message.text or 'general facts'
    today = datetime.now().strftime('%Y-%m-%d')
    # Simulate AI response with prompt (in real use, call an LLM API like xAI's here)
    ai_response = f"PureFact News – {today} – Topic: {query}\n• Test fact: Bot is live and using primary sources [{PRIMARY_SOURCES[0]}]\nSources: {', '.join(PRIMARY_SOURCES)}"
    await update.message.reply_text(ai_response)

def main():
    if TOKEN == 'YOUR_BOT_TOKEN_HERE':
        logging.error("Set your BOT_TOKEN!")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("daily", daily_briefing))
    app.add_handler(CommandHandler("facts", facts_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, facts_query))
    app.run_polling()

if __name__ == '__main__':
    main()
