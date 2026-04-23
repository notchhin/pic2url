# pic2url

Telegram bot that accepts images, stores them on the VPS, and returns a public URL.

## Current deployment
- Bot runs on the VPS under systemd as `pic2url.service`
- Uploaded files are served from `https://img.chhin.tech/<filename>`
- Local storage path on VPS: `/opt/pic2url-uploads`

## Main file
- `main.py`
