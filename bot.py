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
import logging  # For error handling

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

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
    # Table for submissions
    c.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            user_id INTEGER PRIMARY_KEY,
            platform TEXT,
            account_id TEXT,
            package TEXT,
            photo_path TEXT,
            payment_screenshot_path TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')
    # Table for platforms
    c.execute('''
        CREATE TABLE IF NOT EXISTS platforms (
            name TEXT PRIMARY_KEY,
            active INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()
    # Initialize platforms if not already present
    initial_platforms = {
        "instagram": True, "facebook": True, "linkedin": True, "x": True,
        "snapchat": True, "youtube": True, "tiktok": True, "twitter": True,
        "pinterest": True, "reddit": True, "tumblr": True, "wechat": True,
        "whatsapp": True, "telegram": True
    }
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for platform, active in initial_platforms.items():
        c.execute("INSERT OR IGNORE INTO platforms (name, active) VALUES (?, ?)", (platform, 1 if active else 0))
    conn.commit()
    conn.close()

init_db()

# Pricing
pricing = {
    "1000": {"price": 49, "link": "https://www.paypal.com/ncp/payment/8SNLJLF5Z9B6Q"},
    "3000": {"price": 99, "link": "https://www.paypal.com/ncp/payment/QXUFNSAR8ZAV2"},
    "5000": {"price": 149, "link": "https://www.paypal.com/ncp/payment/Q8S4B5GT93JW2"}
}

# Load platforms from database
def load_platforms():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, active FROM platforms")
    platforms = {row[0]: bool(row[1]) for row in c.fetchall()}
    conn.close()
    return platforms

# Define VALID_PLATFORMS globally after initial load
VALID_PLATFORMS = load_platforms()

# Help command with inline buttons
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "👋 *Welcome to SocPeak Boost Bot!* Here's how to use me:\n\n"
        "1. Start with the 'Start Order' button to place an order.\n"
        "2. Specify your platform.\n"
        "3. Provide your link and upload a screenshot.\n"
        "4. Choose a package and pay via QR code.\n"
        "5. Upload payment screenshot for admin approval.\n\n"
        "Use the buttons below to proceed:"
    )
    keyboard = [
        [InlineKeyboardButton("📝 Start Order", callback_data="start_order")],
        [InlineKeyboardButton("❌ Cancel Order", callback_data="cancel_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# Cancel command with inline confirmation
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Cancel", callback_data=f"confirm_cancel_{user_id}"),
         InlineKeyboardButton("❌ No, Keep", callback_data="keep_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚠️ *Are you sure you want to cancel your order?*",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# Start command with inline platform selection (4 buttons per row)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Determine user_id and chat_id based on whether this is a message or callback query
    if update.message:  # Called via /start command
        user_id = update.message.from_user.id
        chat_id = update.message.chat_id
    elif update.callback_query:  # Called via button click
        user_id = update.callback_query.from_user.id
        chat_id = update.callback_query.message.chat_id
    else:
        logger.error("No message or callback query found in update")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM submissions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    # Fully refresh VALID_PLATFORMS
    global VALID_PLATFORMS
    VALID_PLATFORMS = load_platforms()  # Reassign instead of update
    
    active_platforms = [p.capitalize() for p, active in VALID_PLATFORMS.items() if active]
    keyboard = []
    row = []
    for platform in active_platforms:
        row.append(InlineKeyboardButton(platform, callback_data=f"platform_{platform.lower()}"))
        if len(row) == 4:  # 4 buttons per row
            keyboard.append(row)
            row = []
    if row:  # Add any remaining buttons
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "👋 *Welcome to SocPeak Boost Bot!*\n"
        "I’ll help you boost your social media presence. Let’s get started.\n\n"
        "📝 *Step 1:* Please select your platform below:"
    )
    # Send the message to the appropriate chat
    await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# Handle text input (platform, link)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT platform, account_id FROM submissions WHERE user_id = ?", (user_id,))
        result = c.fetchone()

        if result and result[0] and not result[1]:  # Platform exists, expecting account_id/link
            c.execute("UPDATE submissions SET account_id = ? WHERE user_id = ?", (text, user_id))
            conn.commit()
            conn.close()
            keyboard = [
                [InlineKeyboardButton("📸 Upload Screenshot", callback_data="upload_screenshot_prompt")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "✅ *Link saved!*\n"
                "📸 *Step 3:* Please upload a screenshot of your current account using the button below:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "ℹ️ *Please select a platform first!* Use `/start` to begin.",
                parse_mode=ParseMode.MARKDOWN
            )
            conn.close()
    except Exception as e:
        logger.error(f"Error in handle_text: {e}")
        await update.message.reply_text(
            "⚠️ *Something went wrong!* Please try again or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )

# Handle photo upload (account screenshot or payment screenshot)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT platform, account_id, package, photo_path, payment_screenshot_path FROM submissions WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if not result or result[1] is None:  # No platform or account_id
        await update.message.reply_text(
            "⚠️ *Please complete the previous steps first!* Use `/start` to begin.",
            parse_mode=ParseMode.MARKDOWN
        )
        conn.close()
        return

    photo_file = await update.message.photo[-1].get_file()
    
    if result[2] is None:  # No package selected yet, this is the account screenshot
        photo_path = os.path.join(IMAGES_DIR, f"{user_id}_account.jpg")
        await photo_file.download_to_drive(photo_path)
        
        c.execute("UPDATE submissions SET photo_path = ? WHERE user_id = ?", (photo_path, user_id))
        conn.commit()
        conn.close()

        keyboard = [
            [InlineKeyboardButton(f"{k} SocPeak - {v['price']} CHF", callback_data=f"package_{k}") for k, v in pricing.items()],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "✅ *Screenshot received!*\n"
            "💰 *Step 4:* Select your SocPeak package below:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    elif result[2] and result[4] is None:  # Package selected, expecting payment screenshot
        payment_screenshot_path = os.path.join(IMAGES_DIR, f"{user_id}_payment.jpg")
        await photo_file.download_to_drive(payment_screenshot_path)
        
        c.execute("UPDATE submissions SET payment_screenshot_path = ? WHERE user_id = ?", (payment_screenshot_path, user_id))
        conn.commit()
        
        platform, account_id, package = result[0], result[1], result[2]
        conn.close()

        await update.message.reply_text(
            "✅ *Payment screenshot received!*\n"
            "⏳ Your order is under review. We’ll notify you once it’s processed.",
            parse_mode=ParseMode.MARKDOWN
        )

        admin_keyboard = [
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]
        ]
        admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)
        admin_message = (
            f"📋 *New Payment Submission*\n"
            f"👤 User ID: {user_id}\n"
            f"- Platform: *{platform}*\n"
            f"- Account ID: *{account_id}*\n"
            f"- Package: *{package} SocPeak*\n"
            f"Please review the payment screenshot:"
        )
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            parse_mode=ParseMode.MARKDOWN
        )
        async with aiofiles.open(payment_screenshot_path, 'rb') as payment_photo:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=await payment_photo.read(),
                reply_markup=admin_reply_markup
            )
    else:
        keyboard = [
            [InlineKeyboardButton("🔄 Start Over", callback_data="start_order")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "ℹ️ *Order already submitted!* Please wait for admin approval or start over:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        conn.close()

# Handle inline button clicks (user and admin)
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "start_order":
        await start(update, context)
        await query.answer()

    elif data == "cancel_order":
        await cancel(update, context)
        await query.answer()

    elif data.startswith("confirm_cancel_"):
        target_user_id = int(data.split("_")[2])
        if user_id == target_user_id:
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

    elif data == "keep_order":
        await query.message.reply_text(
            "✅ *Order kept!* Continue where you left off.",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()

    elif data.startswith("platform_"):
        platform = data.split("_")[1].capitalize()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO submissions (user_id, platform) VALUES (?, ?)", (user_id, platform))
        conn.commit()
        conn.close()
        keyboard = [
            [InlineKeyboardButton("📝 Enter Link", callback_data="enter_link_prompt")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"✅ *Platform {platform} saved!*\n"
            "📝 *Step 2:* Please send the link you want to BOOST using the button below:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()

    elif data == "enter_link_prompt":
        await query.message.reply_text(
            "📝 *Please send the link you want to BOOST:*",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()

    elif data == "upload_screenshot_prompt":
        await query.message.reply_text(
            "📸 *Please upload a screenshot of your current account:*",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()

    elif data.startswith("package_"):
        package = data.split("_")[1]
        if package in pricing:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE submissions SET package = ? WHERE user_id = ?", (package, user_id))
            conn.commit()
            
            c.execute("SELECT platform FROM submissions WHERE user_id = ?", (user_id,))
            platform = c.fetchone()[0]
            conn.close()

            price = pricing[package]["price"]
            payment_link = pricing[package]["link"]
            keyboard = [
                [InlineKeyboardButton("📸 Upload Payment Screenshot", callback_data="upload_payment_prompt")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                f"🎉 *Order Summary*\n"
                f"- Platform: *{platform}*\n"
                f"- Package: *{package} SocPeak*\n"
                f"- Price: *{price} CHF*\n\n"
                f"💳 *Complete your payment here:*\n{payment_link}\n\n"
                f"📸 *After payment, upload a screenshot of the payment confirmation using the button below:*",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            await query.answer("✅ Package selected!")

    elif data == "upload_payment_prompt":
        await query.message.reply_text(
            "📸 *Please upload a screenshot of your payment confirmation:*",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()

    elif data.startswith("approve_") and user_id == ADMIN_ID:
        target_user_id = int(data.split("_")[1])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE submissions SET status = 'approved' WHERE user_id = ?", (target_user_id,))
        conn.commit()
        
        c.execute("SELECT platform, package FROM submissions WHERE user_id = ?", (target_user_id,))
        result = c.fetchone()
        platform, package = result[0], result[1]
        conn.close()

        keyboard = [
            [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="start_order")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                f"🎉 *Payment Approved!*\n"
                f"Your *{package} SocPeak* boost for *{platform}* is now being processed.\n"
                f"Thank you for choosing SocPeak!"
            ),
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        await query.message.reply_text(
            f"✅ *Approved payment for User ID {target_user_id}!*",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()

    elif data.startswith("reject_") and user_id == ADMIN_ID:
        target_user_id = int(data.split("_")[1])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE submissions SET status = 'rejected' WHERE user_id = ?", (target_user_id,))
        conn.commit()
        conn.close()

        keyboard = [
            [InlineKeyboardButton("🔄 Try Again", callback_data="start_order")],
            [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="start_order")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                f"❌ *Payment Rejected!*\n"
                f"Your payment screenshot was not approved. Please try again or contact support@socpeak.com."
            ),
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        await query.message.reply_text(
            f"❌ *Rejected payment for User ID {target_user_id}!*",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()

    elif data.startswith("admin_") and user_id == ADMIN_ID:
        if data == "admin_add":
            await query.message.reply_text("➕ *Add a new price:* Send `/add_price <SocPeak> <CHF>`", parse_mode=ParseMode.MARKDOWN)
        elif data == "admin_edit":
            await query.message.reply_text("✏️ *Edit a price:* Send `/edit_price <existing SocPeak> <new CHF>`", parse_mode=ParseMode.MARKDOWN)
        elif data == "admin_delete":
            await query.message.reply_text("🗑️ *Delete a price:* Send `/delete_price <SocPeak>`", parse_mode=ParseMode.MARKDOWN)
        elif data == "admin_qr":
            await query.message.reply_text("🔗 *Update QR link:* Send `/update_qr <new QR link>`", parse_mode=ParseMode.MARKDOWN)
        elif data == "admin_view":
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id, platform, account_id, package, photo_path, payment_screenshot_path, status FROM submissions")
            submissions = c.fetchall()
            conn.close()

            if not submissions:
                await query.message.reply_text("ℹ️ *No submissions yet!*", parse_mode=ParseMode.MARKDOWN)
            else:
                for sub in submissions:
                    user_id, platform, account_id, package, photo_path, payment_screenshot_path, status = sub
                    response = (
                        f"📋 *Submission Details:*\n"
                        f"👤 *User ID:* {user_id}\n"
                        f"- Platform: _{platform}_\n"
                        f"- Account ID: _{account_id}_\n"
                        f"- Package: _{package or 'N/A'} SocPeak_\n"
                        f"- Status: _{status}_\n"
                        f"- Account Photo: _{'Uploaded' if photo_path else 'Not Uploaded'}_\n"
                        f"- Payment Screenshot: _{'Uploaded' if payment_screenshot_path else 'Not Uploaded'}_"
                    )
                    keyboard = [
                        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                         InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                    if photo_path and os.path.exists(photo_path):
                        async with aiofiles.open(photo_path, 'rb') as photo:
                            await query.message.reply_photo(photo=await photo.read())
                    if payment_screenshot_path and os.path.exists(payment_screenshot_path):
                        async with aiofiles.open(payment_screenshot_path, 'rb') as payment_photo:
                            await query.message.reply_photo(photo=await payment_photo.read())
        elif data == "admin_change_payment_link":
            await query.message.reply_text(
                "🔗 *Change Payment Link:* Send `/change_payment_link <SocPeak> <new_link>`",
                parse_mode=ParseMode.MARKDOWN
            )
        elif data == "admin_add_platform":
            await query.message.reply_text(
                "➕ *Add a new platform:* Send `/add_platform <platform_name>`",
                parse_mode=ParseMode.MARKDOWN
            )
        elif data == "admin_edit_platform":
            await query.message.reply_text(
                "✏️ *Edit a platform:* Send `/edit_platform <old_name> <new_name>`",
                parse_mode=ParseMode.MARKDOWN
            )
        elif data == "admin_delete_platform":
            await query.message.reply_text(
                "🗑️ *Delete a platform:* Send `/delete_platform <platform_name>`",
                parse_mode=ParseMode.MARKDOWN
            )
        await query.answer()

# Admin panel command with inline buttons
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
        [InlineKeyboardButton("📋 View Submissions", callback_data="admin_view"),
         InlineKeyboardButton("🔗 Change Payment Link", callback_data="admin_change_payment_link")],
        [InlineKeyboardButton("➕ Add Platform", callback_data="admin_add_platform"),
         InlineKeyboardButton("✏️ Edit Platform", callback_data="admin_edit_platform"),
         InlineKeyboardButton("🗑️ Delete Platform", callback_data="admin_delete_platform")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔧 *Admin Control Panel*\nSelect an option below:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# Admin commands (text-based, but triggered via inline buttons)
async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text("⚠️ *Usage:* `/add_price <SocPeak> <CHF>`", parse_mode=ParseMode.MARKDOWN)
        return
    pricing[args[0]] = {"price": int(args[1]), "link": ""}
    await update.message.reply_text(f"✅ *Added:* {args[0]} SocPeak = {args[1]} CHF", parse_mode=ParseMode.MARKDOWN)

async def edit_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 2 or args[0] not in pricing or not args[1].isdigit():
        await update.message.reply_text("⚠️ *Usage:* `/edit_price <existing SocPeak> <new CHF>`", parse_mode=ParseMode.MARKDOWN)
        return
    pricing[args[0]]["price"] = int(args[1])
    await update.message.reply_text(f"✅ *Updated:* {args[0]} SocPeak = {args[1]} CHF", parse_mode=ParseMode.MARKDOWN)

async def delete_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 1 or args[0] not in pricing:
        await update.message.reply_text("⚠️ *Usage:* `/delete_price <SocPeak>`", parse_mode=ParseMode.MARKDOWN)
        return
    del pricing[args[0]]
    await update.message.reply_text(f"✅ *Deleted:* {args[0]} SocPeak package", parse_mode=ParseMode.MARKDOWN)

async def update_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("⚠️ *Usage:* `/update_qr <new QR link>`", parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(f"✅ *QR code updated:* {args[0]}", parse_mode=ParseMode.MARKDOWN)

async def toggle_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    global VALID_PLATFORMS  # Declare global at the beginning
    args = context.args
    if len(args) != 2 or args[0].lower() not in VALID_PLATFORMS or args[1].lower() not in ["on", "off"]:
        await update.message.reply_text("⚠️ *Usage:* `/toggle_platform <platform> <on|off>`", parse_mode=ParseMode.MARKDOWN)
        return
    platform = args[0].lower()
    status = args[1].lower() == "on"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE platforms SET active = ? WHERE name = ?", (1 if status else 0, platform))
    conn.commit()
    conn.close()
    VALID_PLATFORMS = load_platforms()  # Fully refresh
    await update.message.reply_text(f"✅ *Platform {platform.capitalize()} {'activated' if status else 'deactivated'}!*", parse_mode=ParseMode.MARKDOWN)

async def change_payment_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 2 or args[0] not in pricing:
        await update.message.reply_text("⚠️ *Usage:* `/change_payment_link <SocPeak> <new_link>`", parse_mode=ParseMode.MARKDOWN)
        return
    package = args[0]
    new_link = args[1]
    pricing[package]["link"] = new_link
    await update.message.reply_text(f"✅ *Updated payment link for {package} SocPeak:* {new_link}", parse_mode=ParseMode.MARKDOWN)

# New admin commands for managing platforms
async def add_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("⚠️ *Usage:* `/add_platform <platform_name>`", parse_mode=ParseMode.MARKDOWN)
        return
    platform = args[0].lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO platforms (name, active) VALUES (?, 1)", (platform,))
    conn.commit()
    conn.close()
    global VALID_PLATFORMS
    VALID_PLATFORMS = load_platforms()  # Fully refresh
    await update.message.reply_text(f"✅ *Added platform:* {platform.capitalize()}", parse_mode=ParseMode.MARKDOWN)

async def edit_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("⚠️ *Usage:* `/edit_platform <old_name> <new_name>`", parse_mode=ParseMode.MARKDOWN)
        return
    old_name, new_name = args[0].lower(), args[1].lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE platforms SET name = ? WHERE name = ?", (new_name, old_name))
    if c.rowcount == 0:
        await update.message.reply_text(f"⚠️ *Platform {old_name.capitalize()} not found!*", parse_mode=ParseMode.MARKDOWN)
    else:
        conn.commit()
        # Update submissions with the old platform name
        c.execute("UPDATE submissions SET platform = ? WHERE platform = ?", (new_name.capitalize(), old_name.capitalize()))
        conn.commit()
        global VALID_PLATFORMS
        VALID_PLATFORMS = load_platforms()  # Fully refresh
        await update.message.reply_text(f"✅ *Edited platform:* {old_name.capitalize()} → {new_name.capitalize()}", parse_mode=ParseMode.MARKDOWN)
    conn.close()

async def delete_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 *Access denied!*", parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("⚠️ *Usage:* `/delete_platform <platform_name>`", parse_mode=ParseMode.MARKDOWN)
        return
    platform = args[0].lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM platforms WHERE name = ?", (platform,))
    if c.rowcount == 0:
        await update.message.reply_text(f"⚠️ *Platform {platform.capitalize()} not found!*", parse_mode=ParseMode.MARKDOWN)
    else:
        conn.commit()
        # Cancel submissions using this platform
        c.execute("DELETE FROM submissions WHERE platform = ?", (platform.capitalize(),))
        conn.commit()
        global VALID_PLATFORMS
        VALID_PLATFORMS = load_platforms()  # Fully refresh
        await update.message.reply_text(f"✅ *Deleted platform:* {platform.capitalize()}", parse_mode=ParseMode.MARKDOWN)
    conn.close()

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and (update.message or update.callback_query):
        chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ An error occurred. Please try again or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )

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
    application.add_handler(CommandHandler("toggle_platform", toggle_platform))
    application.add_handler(CommandHandler("change_payment_link", change_payment_link))
    application.add_handler(CommandHandler("add_platform", add_platform))
    application.add_handler(CommandHandler("edit_platform", edit_platform))
    application.add_handler(CommandHandler("delete_platform", delete_platform))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
