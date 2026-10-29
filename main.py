
import os
import re
import html
import sqlite3
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, ContextTypes, filters,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {7703752169, 6328753673}
POST_CHANNEL = os.getenv("CHANNEL_ID", "@tokyo_mahwa")
POST_CHANNEL_URL = "https://t.me/tokyo_mahwa"
BOT_USERNAME = os.getenv("BOT_USERNAME", "Animanxa1917bot").lstrip("@")
DB_NAME = "anime.db"

CODE, TITLE, GENRE, MEDIA, REQ_ID, REQ_URL = range(6)


# ---------------- DATABASE ----------------

def connect_db():
    con = sqlite3.connect(DB_NAME)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS anime (
                code TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                genre TEXT NOT NULL,
                media_type TEXT NOT NULL,
                file_id TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE NOT NULL,
                invite_url TEXT NOT NULL
            )
        """)
        # Dastlabki kanalni majburiy obunaga avtomatik qo‘shish
        con.execute(
            "INSERT OR IGNORE INTO required_channels (chat_id, invite_url) VALUES (?, ?)",
            (POST_CHANNEL, POST_CHANNEL_URL),
        )


def get_anime(code):
    with connect_db() as con:
        return con.execute(
            "SELECT * FROM anime WHERE code = ?", (code,)
        ).fetchone()


def get_channels():
    with connect_db() as con:
        return con.execute(
            "SELECT * FROM required_channels ORDER BY id"
        ).fetchall()


def is_admin(user_id):
    return user_id in ADMIN_IDS


# ---------------- MENUS ----------------

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Anime qo‘shish", callback_data="add_anime")],
        [InlineKeyboardButton("➕ Majburiy kanal qo‘shish", callback_data="add_required")],
        [InlineKeyboardButton("📋 Majburiy kanallar", callback_data="list_required")],
        [InlineKeyboardButton("📚 Anime ro‘yxati", callback_data="list_anime")],
    ])


def cancel_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_flow")]
    ])


def subscription_menu():
    rows = []
    for channel in get_channels():
        rows.append([
            InlineKeyboardButton(
                "📢 Kanalga obuna bo‘lish",
                url=channel["invite_url"]
            )
        ])
    rows.append([
        InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub")
    ])
    return InlineKeyboardMarkup(rows)


# ---------------- SUBSCRIPTION ----------------

async def check_all_subscriptions(context, user_id):
    for channel in get_channels():
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel["chat_id"],
                user_id=user_id,
            )
            if member.status in ("left", "kicked"):
                return False
            if member.status == "restricted" and not member.is_member:
                return False
        except Exception:
            logging.exception(
                "Kanal a'zoligini tekshirib bo'lmadi: %s",
                channel["chat_id"]
            )
            return False
    return True


async def require_subscription(update, context, code=None):
    user_id = update.effective_user.id

    if is_admin(user_id):
        return True

    if await check_all_subscriptions(context, user_id):
        return True

    if code:
        context.user_data["pending_code"] = code

    await update.effective_message.reply_text(
        "🔒 Animeni ko‘rish uchun quyidagi kanallarga obuna bo‘ling.\n"
        "Obuna bo‘lgach, «✅ Tekshirish» tugmasini bosing.",
        reply_markup=subscription_menu(),
    )
    return False


# ---------------- ANIME DELIVERY ----------------

async def send_anime(context, chat_id, anime):
    caption = (
        f"🎬 <b>{html.escape(anime['title'])}</b>\n\n"
        f"🎭 Janr: {html.escape(anime['genre'])}\n"
        "🍿 Yoqimli tomosha!"
    )

    kind = anime["media_type"]
    file_id = anime["file_id"]

    if kind == "video":
        await context.bot.send_video(
            chat_id, file_id, caption=caption,
            parse_mode=ParseMode.HTML
        )
    elif kind == "photo":
        await context.bot.send_photo(
            chat_id, file_id, caption=caption,
            parse_mode=ParseMode.HTML
        )
    else:
        await context.bot.send_document(
            chat_id, file_id, caption=caption,
            parse_mode=ParseMode.HTML
        )


async def publish_anime(context, anime):
    caption = (
        f"🎬 <b>{html.escape(anime['title'])}</b>\n\n"
        f"🎭 Janr: {html.escape(anime['genre'])}\n"
        "👇 Ko‘rish uchun pastdagi tugmani bosing!"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎬 Animeni ko‘rish",
            url=f"https://t.me/{BOT_USERNAME}?start=anime_{anime['code']}"
        )
    ]])

    kind = anime["media_type"]
    file_id = anime["file_id"]

    if kind == "video":
        await context.bot.send_video(
            POST_CHANNEL, file_id, caption=caption,
            parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
    elif kind == "photo":
        await context.bot.send_photo(
            POST_CHANNEL, file_id, caption=caption,
            parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
    else:
        await context.bot.send_document(
            POST_CHANNEL, file_id, caption=caption,
            parse_mode=ParseMode.HTML, reply_markup=keyboard
        )


# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith("anime_"):
        code = context.args[0][6:]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", code):
            await update.effective_message.reply_text("❌ Havola noto‘g‘ri.")
            return

        anime = get_anime(code)
        if not anime:
            await update.effective_message.reply_text("❌ Anime topilmadi.")
            return

        if await require_subscription(update, context, code):
            await send_anime(context, update.effective_chat.id, anime)
        return

    rows = []
    if is_admin(update.effective_user.id):
        rows = [[InlineKeyboardButton("⚙️ Admin panel", callback_data="admin_panel")]]

    await update.effective_message.reply_text(
        "🌸 ANIMANXWA BOT\n\n"
        "Kanalimizdagi «🎬 Animeni ko‘rish» tugmasi orqali animelarni tomosha qiling.",
        reply_markup=InlineKeyboardMarkup(rows) if rows else None,
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Siz admin emassiz.")
        return
    await update.effective_message.reply_text("⚙️ Admin panel", reply_markup=admin_menu())


# ---------------- ADD ANIME ----------------

async def begin_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return ConversationHandler.END

    context.user_data["new_anime"] = {}
    await q.message.reply_text("Anime kodini yuboring. Masalan: 1001", reply_markup=cancel_menu())
    return CODE


async def receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", code):
        await update.message.reply_text("Kod faqat harf, raqam, _ yoki - bo‘lsin.")
        return CODE
    if get_anime(code):
        await update.message.reply_text("Bu kod band. Boshqa kod yuboring.")
        return CODE

    context.user_data["new_anime"]["code"] = code
    await update.message.reply_text("Anime nomini yuboring.")
    return TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_anime"]["title"] = update.message.text.strip()[:200]
    await update.message.reply_text("Anime janrini yuboring.")
    return GENRE


async def receive_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_anime"]["genre"] = update.message.text.strip()[:100]
    await update.message.reply_text("Endi anime videosini, rasmini yoki faylini yuboring.")
    return MEDIA


async def receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.message
    if m.video:
        kind, file_id = "video", m.video.file_id
    elif m.photo:
        kind, file_id = "photo", m.photo[-1].file_id
    elif m.document:
        kind, file_id = "document", m.document.file_id
    else:
        await m.reply_text("Video, rasm yoki hujjat yuboring.")
        return MEDIA

    data = context.user_data.get("new_anime", {})
    try:
        with connect_db() as con:
            con.execute(
                "INSERT INTO anime (code,title,genre,media_type,file_id) VALUES (?,?,?,?,?)",
                (data["code"], data["title"], data["genre"], kind, file_id)
            )
        anime = get_anime(data["code"])
        await publish_anime(context, anime)
        await m.reply_text("✅ Anime saqlandi va kanalga joylandi!", reply_markup=admin_menu())
    except Exception:
        logging.exception("Anime saqlash yoki kanalga joylashda xato")
        await m.reply_text(
            "⚠️ Xatolik yuz berdi. Hosting loglarini tekshiring. "
            "Bot kanalga administrator qilib qo‘shilganini tekshiring.",
            reply_markup=admin_menu()
        )

    context.user_data.pop("new_anime", None)
    return ConversationHandler.END


# ---------------- ADD REQUIRED CHANNEL ----------------

async def begin_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return ConversationHandler.END

    context.user_data.pop("new_channel", None)
    await q.message.reply_text(
        "📢 Majburiy kanal ID yoki username yuboring.\n\n"
        "Ommaviy kanal: @kanalusername\n"
        "Private kanal: -1001234567890\n\n"
        "Private kanal ID raqamini Telegram bot orqali aniqlash mumkin.",
        reply_markup=cancel_menu()
    )
    return REQ_ID


async def receive_required_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.text.strip()
    if not (chat_id.startswith("@") or re.fullmatch(r"-100\d+", chat_id)):
        await update.message.reply_text(
            "❌ Noto‘g‘ri format.\n"
            "Ommaviy kanal uchun @username, private kanal uchun -100... ID yuboring."
        )
        return REQ_ID

    context.user_data["new_channel"] = {"chat_id": chat_id}
    await update.message.reply_text(
        "🔗 Endi shu kanalning havolasini yuboring.\n\n"
        "Ommaviy: https://t.me/kanalusername\n"
        "Private: https://t.me/+taklifhavolasi"
    )
    return REQ_URL


async def receive_required_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not re.match(r"^https://t\.me/(.+)$", url):
        await update.message.reply_text("❌ Telegram havolasini https://t.me/... formatida yuboring.")
        return REQ_URL

    chat_id = context.user_data["new_channel"]["chat_id"]
    try:
        with connect_db() as con:
            con.execute(
                "INSERT INTO required_channels (chat_id, invite_url) VALUES (?, ?)",
                (chat_id, url)
            )
        await update.message.reply_text(
            "✅ Majburiy kanal qo‘shildi!\n"
            "Bot o‘sha kanalga administrator qilib qo‘shilganini tekshiring.",
            reply_markup=admin_menu()
        )
    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "ℹ️ Bu kanal allaqachon ro‘yxatda bor.",
            reply_markup=admin_menu()
        )
    except Exception:
        logging.exception("Kanal qo‘shishda xato")
        await update.message.reply_text("❌ Kanalni saqlashda xato.", reply_markup=admin_menu())

    context.user_data.pop("new_channel", None)
    return ConversationHandler.END


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.pop("new_anime", None)
    context.user_data.pop("new_channel", None)
    await q.message.reply_text("❌ Bekor qilindi.", reply_markup=admin_menu())
    return ConversationHandler.END


# ---------------- GENERAL BUTTONS ----------------

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "check_sub":
        if not await check_all_subscriptions(context, q.from_user.id):
            await q.message.reply_text(
                "❌ Hamma kanallarga obuna bo‘lganingizni tekshiring.",
                reply_markup=subscription_menu()
            )
            return

        await q.message.reply_text("✅ Obuna tasdiqlandi!")
        code = context.user_data.pop("pending_code", None)
        if code:
            anime = get_anime(code)
            if anime:
                await send_anime(context, q.message.chat_id, anime)
            else:
                await q.message.reply_text("❌ Anime topilmadi.")
        else:
            await q.message.reply_text("Endi kanal postidagi anime tugmasini bosing.")
        return

    if data == "admin_panel":
        if is_admin(q.from_user.id):
            await q.message.reply_text("⚙️ Admin panel", reply_markup=admin_menu())
        return

    if data == "list_required":
        if not is_admin(q.from_user.id):
            return
        channels = get_channels()
        if not channels:
            await q.message.reply_text("Majburiy kanallar yo‘q.", reply_markup=admin_menu())
            return

        for ch in channels:
            await q.message.reply_text(
                f"📢 {ch['chat_id']}\n{ch['invite_url']}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🗑 O‘chirish",
                        callback_data=f"delete_required_{ch['id']}"
                    )
                ]])
            )
        return

    if data.startswith("delete_required_"):
        if not is_admin(q.from_user.id):
            return
        try:
            channel_id = int(data.replace("delete_required_", "", 1))
            with connect_db() as con:
                con.execute("DELETE FROM required_channels WHERE id = ?", (channel_id,))
            await q.message.reply_text("✅ Majburiy kanal o‘chirildi.", reply_markup=admin_menu())
        except Exception:
            logging.exception("Kanal o‘chirishda xato")
            await q.message.reply_text("❌ O‘chirib bo‘lmadi.")
        return

    if data == "list_anime":
        if not is_admin(q.from_user.id):
            return
        with connect_db() as con:
            rows = con.execute("SELECT code,title FROM anime ORDER BY rowid DESC LIMIT 50").fetchall()
        if not rows:
            await q.message.reply_text("Hozircha anime yo‘q.", reply_markup=admin_menu())
        else:
            text = "📚 Anime ro‘yxati:\n\n" + "\n".join(
                f"{r['code']} — {r['title']}" for r in rows
            )
            await q.message.reply_text(text, reply_markup=admin_menu())


# ---------------- START BOT ----------------

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN Environment Variables ichida yo‘q.")

    init_db()
    app = Application.builder().token(TOKEN).build()

    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(begin_anime, pattern="^add_anime$"),
            CallbackQueryHandler(begin_required, pattern="^add_required$"),
        ],
        states={
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_code)],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
            GENRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_genre)],
            MEDIA: [MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL, receive_media)],
            REQ_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_required_id)],
            REQ_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_required_url)],
        },
        fallbacks=[CallbackQueryHandler(cancel_flow, pattern="^cancel_flow$")],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(conversation)
    app.add_handler(CallbackQueryHandler(buttons))

    logging.info("Animanxwa bot ishga tushmoqda...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
