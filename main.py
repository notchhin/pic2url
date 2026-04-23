import os
import tempfile
import secrets
import logging
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('pic2url')

UPLOAD_DIR = Path(os.environ.get('PIC2URL_UPLOAD_DIR', '/opt/pic2url-uploads'))
PUBLIC_BASE_URL = os.environ.get('PIC2URL_BASE_URL', 'https://img.chhin.tech').rstrip('/')

async def save_locally_and_get_url(local_path: str, suffix: str) -> str:
    """Stores the image on this VPS and returns a permanent public URL."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_suffix = suffix if suffix.startswith('.') else f'.{suffix}'
    filename = f"{secrets.token_urlsafe(12)}{safe_suffix.lower()}"
    target_path = UPLOAD_DIR / filename
    target_path.write_bytes(Path(local_path).read_bytes())
    return f"{PUBLIC_BASE_URL}/{filename}"


async def process_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, suffix: str):
    """Download an image from Telegram, save it on the VPS, and return the public URL."""
    # 1. Get file from Telegram (with specific timeout)
    tg_file = await context.bot.get_file(file_id, read_timeout=30)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # 2. Download locally
        await tg_file.download_to_drive(custom_path=tmp_path)

        # 3. Save to this VPS and return the permanent public URL
        direct = await save_locally_and_get_url(tmp_path, suffix)
        await update.message.reply_text(f"`{direct}`", parse_mode="Markdown")

    except Exception as e:
        logger.exception('Upload failed for file_id=%s suffix=%s', file_id, suffix)
        error_name = type(e).__name__
        error_text = str(e).strip() or 'Unknown error'
        short_error = error_text[:220]
        await update.message.reply_text(f"❌ {error_name}: {short_error}")

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # Check if it's a photo
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        await process_and_upload(update, context, file_id, ".jpg")
    
    # Check if it's a document (image file)
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        doc = update.message.document
        file_id = doc.file_id
        suffix = f".{doc.file_name.split('.')[-1]}" if "." in doc.file_name else ".img"
        await process_and_upload(update, context, file_id, suffix)

def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN env var.")

    # INCREASE TIMEOUTS HERE
    # This prevents the telegram.error.TimedOut you saw in your logs
    t_request = HTTPXRequest(connect_timeout=20, read_timeout=20)

    app = (
        ApplicationBuilder()
        .token(bot_token)
        .request(t_request) # Apply the increased timeouts
        .build()
    )

    # Use a single handler for both types to simplify logic
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_message))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
