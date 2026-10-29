
import os
import re
import html
import sqlite3
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "7703752169"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@tokyo_mahwa")
CHANNEL_URL = "https://t.me/tokyo_mahwa"
BOT_USERNAME = os.getenv(
    "BOT_USERNAME", "Animanxa1917bot"
).lstrip("@")

DB_NAME = "anime.db"

CODE, TITLE, GENRE, MEDIA = range(4)


# ---------- DATABASE ----------

def db():
    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS anime (
                code TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                genre TEXT NOT NULL,
                media_type TEXT NOT NULL,
                file_id TEXT NOT NULL
            )
        """)


def get_anime(code):
    with db() as con:
        return con.execute(
            "SELECT * FROM anime WHERE code = ?",
            (code,),
        ).fetchone()


def get_all_anime():
    with db() as con:
        return con.execute(
            "SELECT * FROM anime ORDER BY rowid DESC"
        ).fetchall()


# ---------- KEYBOARDS ----------

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "➕ Anime qo‘shish", callback_data="add_anime"
        )],
        [InlineKeyboardButton(
            "📚 Anime ro‘yxati", callback_data="list_anime"
        )],
    ])


def subscription_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📢 Kanalga obuna bo‘lish",
            url=CHANNEL_URL,
        )],
        [InlineKeyboardButton(
            "✅ Obunani tekshirish",
            callback_data="check_sub",
        )],
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "❌ Bekor qilish", callback_data="cancel_add"
        )]
    ])


# ---------- SUBSCRIPTION ----------

async def is_subscribed(context, user_id):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_ID,
            user_id=user_id,
        )

        if member.status in ("creator", "administrator", "member"):
            return True

        if member.status == "restricted":
            return bool(getattr(member, "is_member", False))

        return False

    except Exception:
        logging.exception("Obunani tekshirishda xatolik")
        return False


async def require_subscription(update, context, code=None):
    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        return True

    if await is_subscribed(context, user_id):
        return True

    if code:
        context.user_data["pending_anime_code"] = code

    message = (
        "🔒 Animeni ko‘rish uchun avval kanalimizga obuna bo‘ling.\n\n"
        "1. Kanalga kiring va obuna bo‘ling.\n"
        "2. «Obunani tekshirish» tugmasini bosing."
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            message,
            reply_markup=subscription_keyboard(),
        )
    else:
        await update.effective_message.reply_text(
            message,
            reply_markup=subscription_keyboard(),
        )

    return False


# ---------- SEND ANIME ----------

async def send_anime_to_user(context, chat_id, anime):
    caption = (
        f"🎬 <b>{html.escape(anime['title'])}</b>\n\n"
        f"🎭 Janr: {html.escape(anime['genre'])}\n"
        f"🔑 Kod: <code>{html.escape(anime['code'])}</code>\n\n"
        "🍿 Yaxshi tomosha!"
    )

    media_type = anime["media_type"]
    file_id = anime["file_id"]

    if media_type == "video":
        await context.bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    elif media_type == "photo":
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    else:
        await context.bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )


async def publish_to_channel(context, anime):
    caption = (
        f"🎬 <b>{html.escape(anime['title'])}</b>\n\n"
        f"🎭 Janr: {html.escape(anime['genre'])}\n"
        "👇 Animeni bot orqali ko‘rish uchun tugmani bosing!"
    )

    watch_url = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=anime_{anime['code']}"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎬 Animeni ko‘rish", url=watch_url
        )]
    ])

    media_type = anime["media_type"]
    file_id = anime["file_id"]

    if media_type == "video":
        await context.bot.send_video(
            chat_id=CHANNEL_ID,
            video=file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    elif media_type == "photo":
        await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:
        await context.bot.send_document(
            chat_id=CHANNEL_ID,
            document=file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


# ---------- START ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    # Kanal tugmasi orqali kelgan foydalanuvchi
    if args and args[0].startswith("anime_"):
        code = args[0][6:]

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", code):
            await update.effective_message.reply_text(
                "❌ Anime havolasi noto‘g‘ri."
            )
            return

        anime = get_anime(code)

        if not anime:
            await update.effective_message.reply_text(
                "❌ Bu anime topilmadi yoki hali qo‘shilmagan."
            )
            return

        if not await require_subscription(update, context, code):
            return

        await send_anime_to_user(
            context, update.effective_chat.id, anime
        )
        return

    keyboard = []

    if update.effective_user.id == ADMIN_ID:
        keyboard = [[InlineKeyboardButton(
            "⚙️ Admin panel", callback_data="admin_panel"
        )]]

    await update.effective_message.reply_text(
        "🌸 <b>ANIMANXWA BOT</b>\n\n"
        "Anime tomosha qilish botiga xush kelibsiz!\n"
        "Kanalimizdagi «🎬 Animeni ko‘rish» tugmasini bosing.\n\n"
        "🍿 Yoqimli tomosha!",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text(
            "⛔ Sizda admin huquqi yo‘q."
        )
        return

    await update.effective_message.reply_text(
        "⚙️ Admin panel",
        reply_markup=admin_keyboard(),
    )


# ---------- ADD ANIME CONVERSATION ----------

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.message.reply_text("⛔ Ruxsat yo‘q.")
        return ConversationHandler.END

    context.user_data["new_anime"] = {}

    await query.message.reply_text(
        "1️⃣ Anime uchun kod yuboring.\n\n"
        "Masalan: 1001\n"
        "Faqat harf, raqam, _ yoki - ishlating.",
        reply_markup=cancel_keyboard(),
    )
    return CODE


async def receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", code):
        await update.message.reply_text(
            "❌ Kod noto‘g‘ri. Masalan: 1001 yoki anime_1"
        )
        return CODE

    if get_anime(code):
        await update.message.reply_text(
            "❌ Bu kod oldin ishlatilgan. Boshqa kod yuboring."
        )
        return CODE

    context.user_data["new_anime"]["code"] = code

    await update.message.reply_text(
        "2️⃣ Anime nomini yuboring.",
        reply_markup=cancel_keyboard(),
    )
    return TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()

    if not title:
        await update.message.reply_text("Nom bo‘sh bo‘lmasin.")
        return TITLE

    context.user_data["new_anime"]["title"] = title[:200]

    await update.message.reply_text(
        "3️⃣ Anime janrini yuboring.\nMasalan: Jangari, Fantastika",
        reply_markup=cancel_keyboard(),
    )
    return GENRE


async def receive_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    genre = update.message.text.strip()

    if not genre:
        await update.message.reply_text("Janr bo‘sh bo‘lmasin.")
        return GENRE

    context.user_data["new_anime"]["genre"] = genre[:100]

    await update.message.reply_text(
        "4️⃣ Endi animening videosini yoki faylini yuboring.\n\n"
        "Video, rasm yoki hujjat ko‘rinishida yuborishingiz mumkin.\n"
        "Bot uni saqlaydi va kanalga «Animeni ko‘rish» tugmasi bilan joylaydi.",
        reply_markup=cancel_keyboard(),
    )
    return MEDIA


async def receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if message.video:
        media_type = "video"
        file_id = message.video.file_id
    elif message.photo:
        media_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.document:
        media_type = "document"
        file_id = message.document.file_id
    else:
        await message.reply_text(
            "❌ Video, rasm yoki hujjat yuboring."
        )
        return MEDIA

    anime_data = context.user_data.get("new_anime", {})
    code = anime_data.get("code")
    title = anime_data.get("title")
    genre = anime_data.get("genre")

    if not all((code, title, genre)):
        await message.reply_text(
            "❌ Ma’lumotlar topilmadi. Qaytadan /admin buyrug‘ini bosing."
        )
        return ConversationHandler.END

    with db() as con:
        con.execute(
            """
            INSERT INTO anime (code, title, genre, media_type, file_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (code, title, genre, media_type, file_id),
        )

    anime = get_anime(code)

    try:
        await publish_to_channel(context, anime)
        await message.reply_text(
            f"✅ <b>{html.escape(title)}</b> saqlandi va kanalga joylandi!\n\n"
            f"🔑 Anime kodi: <code>{html.escape(code)}</code>\n"
            "📢 Kanal postida «🎬 Animeni ko‘rish» tugmasi bor.",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )
    except Exception:
        logging.exception("Kanalga joylashda xatolik")
        await message.reply_text(
            "⚠️ Anime bazaga saqlandi, ammo kanalga joylanmadi.\n\n"
            "Bot kanal administratori ekanini va post joylash huquqi borligini "
            "tekshiring. So‘ng hosting loglarini tekshiring.",
            reply_markup=admin_keyboard(),
        )

    context.user_data.pop("new_anime", None)
    return ConversationHandler.END


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("new_anime", None)

    await query.message.reply_text(
        "❌ Amal bekor qilindi.",
        reply_markup=admin_keyboard() if query.from_user.id == ADMIN_ID else None,
    )
    return ConversationHandler.END


# ---------- BUTTONS ----------

async def main_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_sub":
        pending_code = context.user_data.get("pending_anime_code")

        if not await is_subscribed(context, query.from_user.id):
            await query.message.reply_text(
                "❌ Obuna aniqlanmadi. Kanalga obuna bo‘lib, qayta tekshiring.",
                reply_markup=subscription_keyboard(),
            )
            return

        await query.message.reply_text("✅ Obuna tasdiqlandi!")

        if pending_code:
            anime = get_anime(pending_code)
            context.user_data.pop("pending_anime_code", None)

            if anime:
                await send_anime_to_user(
                    context, query.message.chat_id, anime
                )
            else:
                await query.message.reply_text(
                    "❌ Bu anime topilmadi."
                )
        else:
            await query.message.reply_text(
                "Endi kanaldagi «🎬 Animeni ko‘rish» tugmasini bosing."
            )

    elif query.data == "admin_panel":
        if query.from_user.id != ADMIN_ID:
            await query.message.reply_text("⛔ Ruxsat yo‘q.")
            return

        await query.message.reply_text(
            "⚙️ Admin panel",
            reply_markup=admin_keyboard(),
        )

    elif query.data == "list_anime":
        if query.from_user.id != ADMIN_ID:
            await query.message.reply_text("⛔ Ruxsat yo‘q.")
            return

        anime_list = get_all_anime()

        if not anime_list:
            await query.message.reply_text("📭 Hozircha anime yo‘q.")
            return

        lines = ["📚 <b>Anime ro‘yxati:</b>\n"]

        for anime in anime_list[:50]:
            lines.append(
                f"🔑 <code>{html.escape(anime['code'])}</code>"
                f" — {html.escape(anime['title'])}"
            )

        await query.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )


# ---------- RUN BOT ----------

def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. Hosting Environment Variables bo‘limiga token kiriting."
        )

    init_db()

    app = Application.builder().token(TOKEN).build()

    add_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add, pattern="^add_anime$")
        ],
        states={
            CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_code)
            ],
            TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)
            ],
            GENRE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_genre)
            ],
            MEDIA: [
                MessageHandler(
                    filters.VIDEO | filters.PHOTO | filters.Document.ALL,
                    receive_media,
                )
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_add, pattern="^cancel_add$")
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(add_conversation)
    app.add_handler(CallbackQueryHandler(main_buttons))

    logging.info("Animanxwa bot ishga tushmoqda...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

