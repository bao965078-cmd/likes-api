import asyncio
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = "8712701750:AAHATuMxEoby2W278bjdLc9PwYorDO8TZsc"
API_URL = "http://127.0.0.1:3031/like"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 BOT LIKE FREE FIRE\n\n"
        "Dùng lệnh:\n"
        "/like UID\n\n"
        "Ví dụ:\n"
        "/like 123456789"
    )


async def like_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Vui lòng nhập UID.\n"
            "Ví dụ: /like 123456789"
        )
        return

    uid = context.args[0]

    if not uid.isdigit():
        await update.message.reply_text("❌ UID phải là số.")
        return

    msg = await update.message.reply_text(
        f"⏳ Đang xử lý UID: {uid}..."
    )

    try:
        response = await asyncio.to_thread(
            requests.get,
            API_URL,
            params={"uid": uid},
            timeout=120
        )

        data = response.json()

        if response.status_code != 200:
            await msg.edit_text(
                f"❌ Lỗi API:\n{data.get('error', 'Unknown error')}"
            )
            return

        result = data.get("result", {})
        user = result.get("User Info", {})
        likes = result.get("Likes Info", {})
        api = result.get("API", {})

        text = (
            "╔══════════════════╗\n"
            "   KUNZ BOT LIKE\n"
            "╚══════════════════╝\n\n"
            f"👤 Tên: {user.get('Account Name', 'N/A')}\n"
            f"🆔 UID: {user.get('Account UID', uid)}\n"
            f"⭐ Level: {user.get('Account Level', 'N/A')}\n\n"
            f"❤️ Like trước: {likes.get('Likes Before', 0)}\n"
            f"💖 Like sau: {likes.get('Likes After', 0)}\n"
            f"➕ Like thêm: {likes.get('Likes Added', 0)}\n\n"
            f"⚡ Thời gian: {api.get('speeds', 'N/A')}\n"
            f"✅ Trạng thái: "
            f"{'Thành công' if api.get('Success') else 'Không thành công'}"
        )

        await msg.edit_text(text)

    except requests.exceptions.Timeout:
        await msg.edit_text("⏱️ API xử lý quá lâu, vui lòng thử lại.")
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("like", like_command))

    print("🤖 Telegram bot đang chạy...")
    app.run_polling()


if __name__ == "__main__":
    main()
