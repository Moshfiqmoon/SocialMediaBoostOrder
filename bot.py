import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv
import aiofiles  # For async file handling

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  # Replace with your Telegram user ID

# Initialize SQLite database
DB_PATH = "submissions.db"
IMAGES_DIR = "user_images"
os.makedirs(IMAGES_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            user_id INTEGER PRIMARY KEY,
            platform TEXT,
            account_id TEXT,
            package TEXT,
            photo_path TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Pricing
pricing = {"1000": 49, "2500": 99, "5000": 179}  # Default pricing (SocPeaks: CHF)
qr_code_base = "https://example.com/payment?amount={}"  # Placeholder QR link
VALID_PLATFORMS = ["facebook", "twitter", "linkedin"]  # Case-insensitive platforms

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "👋 *Welcome to SocPeaks Boost Bot!* Here's how to use me:\n\n"
        "1. Start with `/start` to place an order.\n"
        "2. Specify your platform (e.g., Facebook, Twitter, LinkedIn).\n"
        "3. Provide your Account ID and upload a photo.\n"
        "4. Choose a package and pay via QR code.\n\n"
        "Need to stop? Use `/cancel`.\n"
        "Questions? Contact support@socpeaks.com."
    )
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

# Cancel command
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM submissions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ *Order cancelled!* Start again with `/start`.", parse_mode=ParseMode.MARKDOWN)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    # Clear any existing submission to start fresh
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM submissions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    message = (
        "👋 *Welcome to SocPeaks Boost Bot!*\n"
        "I’ll help you boost your social media presence. Let’s get started.\n\n"
        "📝 *Step 1:* Please specify your platform (e.g., Facebook, Twitter, LinkedIn)."
    )
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

# Handle text input (platform, ID)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip().lower()  # Case-insensitive input

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT platform, account_id FROM submissions WHERE user_id = ?", (user_id,))
        result = c.fetchone()

        if not result:  # New user, expecting platform
            if text not in VALID_PLATFORMS:
                await update.message.reply_text(
                    f"⚠️ *Invalid platform!* Please choose from: {', '.join([p.capitalize() for p in VALID_PLATFORMS])}",
                    parse_mode=ParseMode.MARKDOWN
                )
                conn.close()
                return
            c.execute("INSERT INTO submissions (user_id, platform) VALUES (?, ?)", (user_id, text.capitalize()))
            conn.commit()
            await update.message.reply_text(
                "✅ *Platform saved!*\n"
                "📝 *Step 2:* Now, please send your Account ID (e.g., 123456789).",
                parse_mode=ParseMode.MARKDOWN
            )
        elif result[0] and not result[1]:  # Platform exists, expecting account_id
            if not text.isdigit():
                await update.message.reply_text("⚠️ *Account ID must be numeric!*", parse_mode=ParseMode.MARKDOWN)
                conn.close()
                return
            c.execute("UPDATE submissions SET account_id = ? WHERE user_id = ?", (text, user_id))
            conn.commit()
            await update.message.reply_text(
                "✅ *Account ID saved!*\n"
                "📸 *Step 3:* Please upload a photo for your order.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:  # User has already submitted platform and account_id
            await update.message.reply_text(
                "ℹ️ *You’ve already started an order!* Upload a photo or use `/cancel` to start over.",
                parse_mode=ParseMode.MARKDOWN
            )
        conn.close()
    except Exception as e:
        print(f"Error in handle_text: {e}")
        await update.message.reply_text(
            "⚠️ *Something went wrong!* Please try again or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )

# Handle photo upload and save to database
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT platform, account_id FROM submissions WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if not result or result[1] is None:
        await update.message.reply_text(
            "⚠️ *Please complete the previous steps first!* Use `/start` to begin.",
            parse_mode=ParseMode.MARKDOWN
        )
        conn.close()
        return

    photo_file = await update.message.photo[-1].get_file()
    photo_path = os.path.join(IMAGES_DIR, f"{user_id}.jpg")
    await photo_file.download_to_drive(photo_path)
    
    c.execute("UPDATE submissions SET photo_path = ? WHERE user_id = ?", (photo_path, user_id))
    conn.commit()
    conn.close()

    # Create inline buttons for pricing
    keyboard = [
        [InlineKeyboardButton(f"{k} SocPeaks - {v} CHF", callback_data=f"package_{k}") for k, v in pricing.items()],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "✅ *Photo received!*\n"
        "💰 *Step 4:* Select your SocPeaks package below:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# Handle inline button clicks
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "cancel":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM submissions WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await query.message.reply_text(
            "✅ *Order cancelled!* Start again with `/start`.",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()
        return

    if data.startswith("package_"):
        package = data.split("_")[1]
        if package in pricing:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE submissions SET package = ? WHERE user_id = ?", (package, user_id))
            conn.commit()
            
            c.execute("SELECT platform FROM submissions WHERE user_id = ?", (user_id,))
            platform = c.fetchone()[0]
            conn.close()

            price = pricing[package]
            qr_link = qr_code_base.format(price)
            await query.message.reply_text(
                f"🎉 *Order Summary*\n"
                f"- Platform: *{platform}*\n"
                f"- Package: *{package} SocPeaks*\n"
                f"- Price: *{price} CHF*\n\n"
                f"💳 *Scan this QR code to complete your payment:*\n{qr_link}\n\n"
                f"Thank you for choosing SocPeaks! Once paid, your boost will be processed.",
                parse_mode=ParseMode.MARKDOWN
            )
            await query.answer("✅ Package selected!")

    elif data.startswith("admin_") and user_id == ADMIN_ID:
        if data == "admin_add":
            await query.message.reply_text("➕ *Add a new price:* Send `/add_price <SocPeaks> <CHF>`", parse_mode=ParseMode.MARKDOWN)
        elif data == "admin_edit":
            await query.message.reply_text("✏️ *Edit a price:* Send `/edit_price <existing SocPeaks> <new CHF>`", parse_mode=ParseMode.MARKDOWN)
        elif data == "admin_delete":
            await query.message.reply_text("🗑️ *Delete a price:* Send `/delete_price <SocPeaks>`", parse_mode=ParseMode.MARKDOWN)
        elif data == "admin_qr":
            await query.message.reply_text("🔗 *Update QR link:* Send `/update_qr <new QR link>`", parse_mode=ParseMode.MARKDOWN)
        elif data == "admin_view":
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id, platform, account_id, package, photo_path FROM submissions")
            submissions = c.fetchall()
            conn.close()

            if not submissions:
                await query.message.reply_text("ℹ️ *No submissions yet!*", parse_mode=ParseMode.MARKDOWN)
            else:
                for sub in submissions:
                    user_id, platform, account_id, package, photo_path = sub
                    response = (
                        f"📋 *Recent Submissions:*\n"
                        f"👤 *User ID:* {user_id}\n"
                        f"- Platform: _{platform}_\n"
                        f"- Account ID: _{account_id}_\n"
                        f"- Package: _{package or 'N/A'} SocPeaks_\n"
                        f"- Photo: _Uploaded_"
                    )
                    await query.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
                    if photo_path and os.path.exists(photo_path):
                        async with aiofiles.open(photo_path, 'rb') as photo:
                            await query.message.reply_photo(photo=await photo.read())
        await query.answer()

# Admin panel command
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return

    keyboard = [
        [InlineKeyboardButton("➕ Add Price", callback_data="admin_add"),
         InlineKeyboardButton("✏️ Edit Price", callback_data="admin_edit")],
        [InlineKeyboardButton("🗑️ Delete Price", callback_data="admin_delete"),
         InlineKeyboardButton("🔗 Update QR", callback_data="admin_qr")],
        [InlineKeyboardButton("📋 View Submissions", callback_data="admin_view")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔧 *Admin Control Panel*\nSelect an option below:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# Admin commands
async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text("⚠️ *Usage:* `/add_price <SocPeaks> <CHF>`", parse_mode=ParseMode.MARKDOWN)
        return
    pricing[args[0]] = int(args[1])
    await update.message.reply_text(f"✅ *Added:* {args[0]} SocPeaks = {args[1]} CHF", parse_mode=ParseMode.MARKDOWN)

async def edit_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 2 or args[0] not in pricing or not args[1].isdigit():
        await update.message.reply_text("⚠️ *Usage:* `/edit_price <existing SocPeaks> <new CHF>`", parse_mode=ParseMode.MARKDOWN)
        return
    pricing[args[0]] = int(args[1])
    await update.message.reply_text(f"✅ *Updated:* {args[0]} SocPeaks = {args[1]} CHF", parse_mode=ParseMode.MARKDOWN)

async def delete_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 1 or args[0] not in pricing:
        await update.message.reply_text("⚠️ *Usage:* `/delete_price <SocPeaks>`", parse_mode=ParseMode.MARKDOWN)
        return
    del pricing[args[0]]
    await update.message.reply_text(f"✅ *Deleted:* {args[0]} SocPeaks package", parse_mode=ParseMode.MARKDOWN)

async def update_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global qr_code_base
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("⚠️ *Usage:* `/update_qr <new QR link>`", parse_mode=ParseMode.MARKDOWN)
        return
    qr_code_base = args[0]
    await update.message.reply_text(f"✅ *QR code updated:* {qr_code_base}", parse_mode=ParseMode.MARKDOWN)

# Main function
def main():
    application = Application.builder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_button))
    
    # Admin commands
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("add_price", add_price))
    application.add_handler(CommandHandler("edit_price", edit_price))
    application.add_handler(CommandHandler("delete_price", delete_price))
    application.add_handler(CommandHandler("update_qr", update_qr))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()