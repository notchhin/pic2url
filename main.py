import os
import tempfile
import secrets
import logging
from pathlib import Path
import httpx  # Use httpx instead of requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('pic2url')

UPLOAD_DIR = Path(os.environ.get('PIC2URL_UPLOAD_DIR', '/opt/pic2url-uploads'))
PUBLIC_BASE_URL = os.environ.get('PIC2URL_BASE_URL', 'https://chhin.tech/pic2url').rstrip('/')

FREEIMAGE_ENDPOINT = "https://freeimage.host/api/1/upload"
FALLBACK_UPLOAD_ENDPOINT = "https://uguu.se/upload.php"

async def upload_to_freeimage_async(local_path: str, api_key: str) -> dict:
    """Uploads image asynchronously using httpx."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(local_path, "rb") as f:
            files = {"source": f}
            data = {
                "key": api_key,
                "action": "upload",
                "format": "json",
            }
            # The async call allows other bot functions to run while waiting
            response = await client.post(FREEIMAGE_ENDPOINT, data=data, files=files)
            
        if response.status_code != 200:
            raise RuntimeError(f"FreeImage returned {response.status_code}: {response.text[:500]}")

        payload = response.json()
        if payload.get('status_code') and payload.get('status_code') != 200:
            raise RuntimeError(f"FreeImage API error {payload.get('status_code')}: {payload.get('status_txt') or payload}")

        return payload


async def upload_to_fallback_async(local_path: str) -> str:
    """Uploads image to Uguu when FreeImage is failing."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        with open(local_path, "rb") as f:
            files = {"files[]": (Path(local_path).name, f)}
            response = await client.post(FALLBACK_UPLOAD_ENDPOINT, files=files)

        if response.status_code != 200:
            raise RuntimeError(f"Uguu returned {response.status_code}: {response.text[:500]}")

        payload = response.json()
        files_meta = payload.get('files') or []
        url = files_meta[0].get('url') if files_meta else None
        if not url or not str(url).startswith('http'):
            raise RuntimeError(f"Uguu unexpected response: {payload}")
        return url

async def save_locally_and_get_url(local_path: str, suffix: str) -> str:
    """Stores the image on this VPS and returns a permanent public URL."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_suffix = suffix if suffix.startswith('.') else f'.{suffix}'
    filename = f"{secrets.token_urlsafe(12)}{safe_suffix.lower()}"
    target_path = UPLOAD_DIR / filename
    target_path.write_bytes(Path(local_path).read_bytes())
    return f"{PUBLIC_BASE_URL}/{filename}"


async def process_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, suffix: str):
    """Core logic to download from TG and upload to FreeImage."""
    api_key = os.environ.get("FREEIMAGE_KEY")
    if not api_key:
        await update.message.reply_text("❌ Server missing FREEIMAGE_KEY.")
        return

    # 1. Get file from Telegram (with specific timeout)
    tg_file = await context.bot.get_file(file_id, read_timeout=30)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # 2. Download locally
        await tg_file.download_to_drive(custom_path=tmp_path)

        # 3. Save to this VPS first (permanent), then fall back to remote hosts only if local storage fails
        direct = None
        try:
            direct = await save_locally_and_get_url(tmp_path, suffix)
        except Exception as local_error:
            logger.warning("Local VPS save failed, falling back to remote upload: %s", local_error)
            try:
                payload = await upload_to_freeimage_async(tmp_path, api_key)
                image = payload.get("image", {})
                direct = image.get("url") or image.get("display_url")
                if not direct:
                    raise RuntimeError("FreeImage upload succeeded, but no direct URL was returned")
            except Exception as upload_error:
                logger.warning("FreeImage failed, falling back to Uguu: %s", upload_error)
                direct = await upload_to_fallback_async(tmp_path)

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
