# pic2url

Telegram bot that accepts images, stores them on the VPS, and returns a public URL from your own domain.

## Current deployment
- Bot runs on the VPS under systemd as `pic2url.service`
- Uploaded files are served from `https://img.chhin.tech/<filename>`
- Local storage path on VPS: `/opt/pic2url-uploads`

## Environment
- `TELEGRAM_BOT_TOKEN`
- `PIC2URL_UPLOAD_DIR` (optional)
- `PIC2URL_BASE_URL` (optional)

## Main file
- `main.py`
