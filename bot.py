import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("ADMIN_ID", "0").split(",")
    if x.strip().isdigit()
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"
USERS_FILE = DATA_DIR / "users.json"

bot = Bot(token=BOT_TOKEN)

public_router = Router()
admin_router = Router()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Middleware ────────────────────────────────────────────────────────────────

class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user is None or not is_admin(user.id):
            return

        return await handler(event, data)


admin_router.message.middleware(AdminOnlyMiddleware())
admin_router.callback_query.middleware(AdminOnlyMiddleware())


# ── Config helpers ───────────────────────────────────────────────────────────

def load_config() -> dict:
    defaults = {
        "image_file_id": None,
        "image_caption": "Welcome!",
        "apk_file_id": None,
        "apk_caption": "Download our app!",
    }
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        defaults.update(saved)
    return defaults


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ── User DB helpers ──────────────────────────────────────────────────────────

def load_users() -> dict:
    if USERS_FILE.exists():
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_users(users: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def add_user(user_id: int, username: str | None, first_name: str) -> bool:
    """Add or update a user. Returns True if the user is brand new."""
    users = load_users()
    is_new = str(user_id) not in users
    users[str(user_id)] = {
        "username": username,
        "first_name": first_name,
        "joined": datetime.now(timezone.utc).isoformat() if is_new else users.get(str(user_id), {}).get("joined"),
    }
    save_users(users)
    return is_new


def get_all_user_ids() -> list[int]:
    return [int(uid) for uid in load_users()]


def get_stats() -> dict:
    users = load_users()
    return {"total": len(users)}


# ── States ───────────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    waiting_image = State()
    waiting_image_caption = State()
    waiting_apk = State()
    waiting_apk_caption = State()
    waiting_broadcast = State()


# ── /start → Age check → Gender → Deliver content ───────────────────────────

@public_router.message(Command("start"))
async def cmd_start(message: Message):
    if is_admin(message.from_user.id):
        pass  # admins also go through the flow

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes, I'm 18+", callback_data="age_yes"),
            InlineKeyboardButton(text="❌ No", callback_data="age_no"),
        ]
    ])
    await message.answer(
        "🔞 <b>Age Verification</b>\n\n"
        "You must be <b>18 years or older</b> to use this bot.\n\n"
        "Are you 18+?",
        reply_markup=kb,
        parse_mode="HTML",
    )


@public_router.callback_query(F.data == "age_no")
async def cb_age_no(callback: CallbackQuery):
    await callback.message.edit_text("🚫 Sorry, you must be 18+ to use this bot. Goodbye!")
    await callback.answer()


@public_router.callback_query(F.data == "age_yes")
async def cb_age_yes(callback: CallbackQuery):
    user = callback.from_user
    is_new = add_user(user.id, user.username, user.first_name)

    await callback.message.edit_text("✅ <b>Verified!</b> Sending your content...", parse_mode="HTML")

    cfg = load_config()

    if not cfg["image_file_id"]:
        await callback.message.answer("⚠️ Bot is not configured yet. Please contact the admin.")
        await callback.answer()
        return

    await callback.message.answer_photo(
        photo=cfg["image_file_id"],
        caption=cfg["image_caption"],
    )

    if cfg["apk_file_id"]:
        await callback.message.answer_document(
            document=cfg["apk_file_id"],
            caption=cfg["apk_caption"],
        )

    await callback.answer()

    if is_new:
        await notify_admins_new_user(user.id, user.username, user.first_name)


async def notify_admins_new_user(user_id: int, username: str | None, first_name: str):
    stats = get_stats()
    uname = f"@{username}" if username else "N/A"
    text = (
        "🆕 <b>New User Joined!</b>\n\n"
        f"👤 Name: <b>{first_name}</b>\n"
        f"🔗 Username: {uname}\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"📊 Total users: <b>{stats['total']}</b>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass


# ── Admin panel ──────────────────────────────────────────────────────────────

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🖼 Change Image", callback_data="adm_image")],
        [InlineKeyboardButton(text="✏️ Change Image Caption", callback_data="adm_img_cap")],
        [InlineKeyboardButton(text="📦 Change APK", callback_data="adm_apk")],
        [InlineKeyboardButton(text="✏️ Change APK Caption", callback_data="adm_apk_cap")],
        [
            InlineKeyboardButton(text="📊 Stats", callback_data="adm_stats"),
            InlineKeyboardButton(text="👁 Preview", callback_data="adm_preview"),
        ],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="adm_broadcast")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@admin_router.message(Command("adm"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    cfg = load_config()
    stats = get_stats()
    status_lines = [
        "⚙️ <b>Admin Panel</b>\n",
        f"🖼 Image: {'Set ✅' if cfg['image_file_id'] else 'Not set ❌'}",
        f"✏️ Image caption: {cfg['image_caption']}",
        f"📦 APK: {'Set ✅' if cfg['apk_file_id'] else 'Not set ❌'}",
        f"✏️ APK caption: {cfg['apk_caption']}\n",
        f"👥 Users: <b>{stats['total']}</b>",
    ]
    await message.answer(
        "\n".join(status_lines),
        reply_markup=admin_panel_keyboard(),
        parse_mode="HTML",
    )


# ── Admin callbacks ──────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "adm_image")
async def cb_change_image(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_image)
    await callback.message.answer("🖼 Send the new image (as a photo):")
    await callback.answer()


@admin_router.callback_query(F.data == "adm_img_cap")
async def cb_change_image_caption(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_image_caption)
    await callback.message.answer("✏️ Send the new image caption text:")
    await callback.answer()


@admin_router.callback_query(F.data == "adm_apk")
async def cb_change_apk(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_apk)
    await callback.message.answer("📦 Send the APK file (as a document):")
    await callback.answer()


@admin_router.callback_query(F.data == "adm_apk_cap")
async def cb_change_apk_caption(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_apk_caption)
    await callback.message.answer("✏️ Send the new APK caption text:")
    await callback.answer()


@admin_router.callback_query(F.data == "adm_stats")
async def cb_stats(callback: CallbackQuery):
    stats = get_stats()
    users = load_users()

    recent = sorted(users.values(), key=lambda u: u.get("joined", ""), reverse=True)[:5]
    recent_lines = []
    for u in recent:
        uname = f"@{u['username']}" if u.get("username") else u.get("first_name", "Unknown")
        recent_lines.append(f"  👤 {uname}")

    text = (
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total users: <b>{stats['total']}</b>\n"
    )

    if recent_lines:
        text += "\n🕐 <b>Recent users:</b>\n" + "\n".join(recent_lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Panel", callback_data="adm_back")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@admin_router.callback_query(F.data == "adm_preview")
async def cb_preview(callback: CallbackQuery):
    cfg = load_config()
    if not cfg["image_file_id"]:
        return await callback.answer("❌ Image not set yet!", show_alert=True)

    await callback.message.answer_photo(
        photo=cfg["image_file_id"],
        caption=cfg["image_caption"],
    )
    if cfg["apk_file_id"]:
        await callback.message.answer_document(
            document=cfg["apk_file_id"],
            caption=cfg["apk_caption"],
        )
    await callback.answer()


@admin_router.callback_query(F.data == "adm_broadcast")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_broadcast)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="adm_cancel")]
    ])
    await callback.message.answer(
        "📢 <b>Broadcast</b>\n\n"
        "Send a message now. It will be forwarded to <b>all users</b>.\n\n"
        "You can send text, photo, video, document, or sticker.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@admin_router.callback_query(F.data == "adm_cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Cancelled.")
    await callback.answer()


@admin_router.callback_query(F.data == "adm_back")
async def cb_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    cfg = load_config()
    stats = get_stats()
    status_lines = [
        "⚙️ <b>Admin Panel</b>\n",
        f"🖼 Image: {'Set ✅' if cfg['image_file_id'] else 'Not set ❌'}",
        f"✏️ Image caption: {cfg['image_caption']}",
        f"📦 APK: {'Set ✅' if cfg['apk_file_id'] else 'Not set ❌'}",
        f"✏️ APK caption: {cfg['apk_caption']}\n",
        f"👥 Users: <b>{stats['total']}</b>",
    ]
    await callback.message.edit_text(
        "\n".join(status_lines),
        reply_markup=admin_panel_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── State handlers ───────────────────────────────────────────────────────────

@admin_router.message(AdminStates.waiting_image, F.photo)
async def handle_new_image(message: Message, state: FSMContext):
    cfg = load_config()
    cfg["image_file_id"] = message.photo[-1].file_id
    save_config(cfg)
    await state.clear()
    await message.answer("✅ Image updated!", reply_markup=admin_panel_keyboard())


@admin_router.message(AdminStates.waiting_image_caption, F.text)
async def handle_new_image_caption(message: Message, state: FSMContext):
    cfg = load_config()
    cfg["image_caption"] = message.text
    save_config(cfg)
    await state.clear()
    await message.answer("✅ Image caption updated!", reply_markup=admin_panel_keyboard())


@admin_router.message(AdminStates.waiting_apk, F.document)
async def handle_new_apk(message: Message, state: FSMContext):
    cfg = load_config()
    cfg["apk_file_id"] = message.document.file_id
    save_config(cfg)
    await state.clear()
    await message.answer("✅ APK updated!", reply_markup=admin_panel_keyboard())


@admin_router.message(AdminStates.waiting_apk_caption, F.text)
async def handle_new_apk_caption(message: Message, state: FSMContext):
    cfg = load_config()
    cfg["apk_caption"] = message.text
    save_config(cfg)
    await state.clear()
    await message.answer("✅ APK caption updated!", reply_markup=admin_panel_keyboard())


@admin_router.message(AdminStates.waiting_broadcast)
async def handle_broadcast(message: Message, state: FSMContext):
    await state.clear()
    user_ids = get_all_user_ids()
    total = len(user_ids)
    success = 0
    failed = 0

    status_msg = await message.answer(f"📢 Broadcasting to <b>{total}</b> users...", parse_mode="HTML")

    for uid in user_ids:
        try:
            await message.copy_to(uid)
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"📢 <b>Broadcast Complete</b>\n\n"
        f"✅ Sent: <b>{success}</b>\n"
        f"❌ Failed: <b>{failed}</b>\n"
        f"👥 Total: <b>{total}</b>",
        parse_mode="HTML",
    )


# ── Entrypoint ───────────────────────────────────────────────────────────────

async def main():
    dp = Dispatcher()
    dp.include_router(admin_router)
    dp.include_router(public_router)
    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
