# Spread Bot

A Telegram bot built with aiogram 3 that sends a configurable image + APK to users on `/start`. Admins can update all content via `/adm`.

## Setup

1. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables**

   Copy `.env.example` to `.env` and fill in your values:

   ```bash
   cp .env.example .env
   ```

   | Variable    | Description                                |
   | ----------- | ------------------------------------------ |
   | `BOT_TOKEN` | Telegram bot token from @BotFather         |
   | `ADMIN_ID`  | Comma-separated Telegram user IDs of admins |

3. **Run the bot**

   ```bash
   python bot.py
   ```

## Usage

### Users
- `/start` — Receive the configured image and APK.

### Admin (matching `ADMIN_ID`)
- `/adm` — Open the admin panel to:
  - Change the welcome image
  - Change the image caption
  - Change the APK file
  - Change the APK caption
  - Preview what users see on `/start`

Configuration is persisted in `data/config.json`.
