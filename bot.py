import asyncio
import os
from web3 import Web3, AsyncWeb3
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.error import TelegramError
from dotenv import load_dotenv

# --- Configuration ---
# Load environment variables from a .env file for local development
load_dotenv()

# Get sensitive data from environment variables
# On Render.com, you will set these in the 'Environment' section for your service
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8359506520:AAGwfIyp67laNrAVpaTRr4WPXhjLhMUzFyM")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") # IMPORTANT: Your channel/group ID (e.g., '@YourChannelName' or '-1001234567890')
QUICKNODE_BSC_URL = os.getenv("QUICKNODE_BSC_URL") # IMPORTANT: Your QuickNode WebSocket URL (e.g., 'wss://example.rpc.url')

# --- AgamaCoin & Purchase Details ---
TOKEN_CONTRACT_ADDRESS = "0x2119de8f257d27662991198389E15Bf8d1F4aB24"
MIN_PURCHASE_BNB = 0.025
TOKEN_LOGO_URL = "https://www.agamacoin.com/agama-logo-new.png"
TOKEN_NAME = "AgamaCoin"
BSCSCAN_TOKEN_URL = f"https://bscscan.com/token/{TOKEN_CONTRACT_ADDRESS}"
# Use the static method from the base Web3 class for conversion
MIN_PURCHASE_WEI = Web3.to_wei(MIN_PURCHASE_BNB, 'ether')
REMINDER_INTERVAL_SECONDS = 600 # 10 minutes

# --- Global State Management ---
# These will hold the background tasks
monitoring_task = None
reminder_task = None

# --- Input Validation ---
def validate_config():
    """Checks if all necessary environment variables are set."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Error: TELEGRAM_BOT_TOKEN is not set.")
    if not TELEGRAM_CHAT_ID:
        raise ValueError("Error: TELEGRAM_CHAT_ID is not set.")
    if not QUICKNODE_BSC_URL or not QUICKNODE_BSC_URL.startswith('wss://'):
        raise ValueError("Error: QUICKNODE_BSC_URL is not set or is invalid.")
    print("Configuration validated successfully.")

# --- Menu and Keyboard Functions ---
def get_main_menu_keyboard():
    """Returns the main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("📢 Manage Price Alerts", callback_data='menu_alerts')],
        [InlineKeyboardButton("⏰ Manage Reminders", callback_data='menu_reminders')],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_alerts_menu_keyboard():
    """Returns the price alerts submenu keyboard."""
    keyboard = [
        [InlineKeyboardButton("▶️ Start Price Alerts", callback_data='start_monitoring')],
        [InlineKeyboardButton("⏹️ Stop Price Alerts", callback_data='stop_monitoring')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='main_menu')],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_reminders_menu_keyboard():
    """Returns the reminders submenu keyboard."""
    keyboard = [
        [InlineKeyboardButton("▶️ Start Reminders", callback_data='start_reminder')],
        [InlineKeyboardButton("⏹️ Stop Reminders", callback_data='stop_reminder')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='main_menu')],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Telegram Bot Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the main menu."""
    try:
        await update.message.reply_text(
            '👋 Welcome to the AgamaCoin Bot Control Panel!\n\n'
            'Please choose an option below:',
            reply_markup=get_main_menu_keyboard()
        )
    except TelegramError as te:
        print(f"❌ Telegram API Error on /start command: {te}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses all button clicks and routes them to the correct function."""
    global monitoring_task, reminder_task
    query = update.callback_query
    await query.answer()

    action = query.data
    
    try:
        # Main Menu Navigation
        if action == 'main_menu':
            await query.edit_message_text('Please choose an option below:', reply_markup=get_main_menu_keyboard())
        elif action == 'menu_alerts':
            await query.edit_message_text('Price Alert Controls:', reply_markup=get_alerts_menu_keyboard())
        elif action == 'menu_reminders':
            await query.edit_message_text('Presale Reminder Controls:', reply_markup=get_reminders_menu_keyboard())
        
        # Price Alert Actions
        elif action == 'start_monitoring':
            if monitoring_task and not monitoring_task.done():
                await query.edit_message_text("✅ Price alert monitoring is already running.", reply_markup=get_alerts_menu_keyboard())
            else:
                await query.edit_message_text("▶️ Starting price alert monitoring...", reply_markup=get_alerts_menu_keyboard())
                monitoring_task = asyncio.create_task(price_alert_loop(context.bot))
                print("Price alert monitoring task started.")
        elif action == 'stop_monitoring':
            if monitoring_task and not monitoring_task.done():
                monitoring_task.cancel()
                await query.edit_message_text("⏹️ Price alert monitoring stopped.", reply_markup=get_alerts_menu_keyboard())
                print("Price alert monitoring task cancelled.")
            else:
                await query.edit_message_text("ℹ️ Price alert monitoring is not currently running.", reply_markup=get_alerts_menu_keyboard())

        # Reminder Actions
        elif action == 'start_reminder':
            if reminder_task and not reminder_task.done():
                await query.edit_message_text("✅ Presale reminders are already running.", reply_markup=get_reminders_menu_keyboard())
            else:
                await query.edit_message_text("▶️ Starting presale reminders...", reply_markup=get_reminders_menu_keyboard())
                reminder_task = asyncio.create_task(reminder_loop(context.bot))
                print("Reminder task started.")
        elif action == 'stop_reminder':
            if reminder_task and not reminder_task.done():
                reminder_task.cancel()
                await query.edit_message_text("⏹️ Presale reminders stopped.", reply_markup=get_reminders_menu_keyboard())
                print("Reminder task cancelled.")
            else:
                await query.edit_message_text("ℹ️ Presale reminders are not currently running.", reply_markup=get_reminders_menu_keyboard())

    except TelegramError as te:
        print(f"❌ Telegram API Error during button callback '{action}': {te}")
    except Exception as e:
        print(f"❌ An unexpected error occurred during button callback '{action}': {e}")

# --- Alert & Reminder Sending Functions ---
async def send_telegram_alert(bot: Bot, bnb_amount, tx_hash):
    """Formats and sends a buy alert."""
    bnb_amount_formatted = f"{bnb_amount:.4f}"
    message_text = (
        f"🚀 *New {TOKEN_NAME} Buy Alert!* 🚀\n\n"
        f"A new investor has just joined the AgamaCoin family!\n\n"
        f"💰 *Amount:* {bnb_amount_formatted} BNB\n\n"
        f"Let's give them a warm welcome! 🔥"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ View Transaction", url=f"https://bscscan.com/tx/{tx_hash}")]])
    try:
        await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=TOKEN_LOGO_URL, caption=message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        print(f"✅ Alert sent for transaction: {tx_hash}")
    except TelegramError as te:
        print(f"❌ Telegram API Error sending alert: {te}")

async def send_reminder_message(bot: Bot):
    """Sends the recurring presale reminder message."""
    message_text = "⏰ *Friendly Reminder!* ⏰\n\nThe AgamaCoin presale is your golden opportunity. Don't miss out on securing your tokens at the best price!\n\n*Buy now before it ends!*"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💰 Buy AgamaCoin Now!", url=BSCSCAN_TOKEN_URL)]])
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        print("⏰ Reminder message sent.")
    except TelegramError as te:
        print(f"❌ Telegram API Error sending reminder: {te}")

# --- Background Loops ---
async def reminder_loop(bot: Bot):
    """Sends a reminder message every X seconds."""
    print("✅ Reminder loop started.")
    try:
        while True:
            await send_reminder_message(bot)
            await asyncio.sleep(REMINDER_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        print("⏹️ Reminder loop cancelled.")
    finally:
        print("Reminder loop has shut down.")

async def price_alert_loop(bot: Bot):
    """The main event loop that listens for new blocks and transactions."""
    print("Connecting to BSC for price alerts...")
    w3 = AsyncWeb3(AsyncWeb3.AsyncWebsocketProvider(QUICKNODE_BSC_URL))
    
    if not await w3.is_connected():
        print("❌ Failed to connect to the BSC node for price alerts.")
        return

    print("✅ Successfully connected to BSC. Creating block filter...")
    block_filter = await w3.eth.create_filter('latest')
    print("✅ Block filter created. Monitoring for buys...")

    try:
        while True:
            new_blocks = await block_filter.get_new_entries()
            for block_hash in new_blocks:
                try:
                    block = await w3.eth.get_block(block_hash, full_transactions=True)
                    if block and block.transactions:
                        for tx in block.transactions:
                            if tx.to and tx.to.lower() == TOKEN_CONTRACT_ADDRESS.lower() and tx.value >= MIN_PURCHASE_WEI:
                                bnb_value = w3.from_wei(tx.value, 'ether')
                                print(f"✔️  Valid purchase detected! Hash: {tx.hash.hex()}")
                                await send_telegram_alert(bot, bnb_value, tx.hash.hex())
                except Exception as e:
                    print(f"Error processing block {block_hash.hex()}: {e}")
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        print("⏹️ Price alert loop cancelled.")
    except Exception as e:
        print(f"An error occurred in the price alert loop: {e}. Reconnecting in 15s...")
        await asyncio.sleep(15)
    finally:
        print("Price alert loop has shut down.")

# --- Main Execution ---
def main():
    """Starts the bot application."""
    try:
        validate_config()
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CallbackQueryHandler(button_callback))
        print("Bot is starting... Press Ctrl-C to stop.")
        application.run_polling()
    except (ValueError, ConnectionError) as e:
        print(f"CRITICAL ERROR: {e}")
    except KeyboardInterrupt:
        print("\nBot stopped by user.")

if __name__ == "__main__":
    main()
