import asyncio
import os
from web3 import Web3, AsyncWeb3
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
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

# --- Global State Management ---
# This will hold the background task that monitors the blockchain
monitoring_task = None

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

# --- Telegram Bot Functions ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a message with the control buttons when the /start command is issued."""
    keyboard = [
        [InlineKeyboardButton("▶️ Start Alerts", callback_data='start_monitoring')],
        [InlineKeyboardButton("⏹️ Stop Alerts", callback_data='stop_monitoring')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        '👋 Welcome to the AgamaCoin Alert Bot!\n\n'
        'Use the buttons below to control the buy alerts.',
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses the CallbackQuery and starts or stops the monitoring task."""
    global monitoring_task
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    if query.data == 'start_monitoring':
        if monitoring_task and not monitoring_task.done():
            await query.edit_message_text(text="✅ Alert monitoring is already running.")
        else:
            await query.edit_message_text(text="▶️ Starting alert monitoring...")
            # Start the main_loop as a background task
            monitoring_task = asyncio.create_task(main_loop(context.bot))
            print("Monitoring task started via button.")
    
    elif query.data == 'stop_monitoring':
        if monitoring_task and not monitoring_task.done():
            monitoring_task.cancel()
            await query.edit_message_text(text="⏹️ Alert monitoring stopped.")
            print("Monitoring task cancelled via button.")
        else:
            await query.edit_message_text(text="ℹ️ Alert monitoring is not currently running.")


async def send_telegram_alert(bot: Bot, bnb_amount, tx_hash):
    """Formats and sends a buy alert to the specified Telegram channel."""
    bnb_amount_formatted = f"{bnb_amount:.4f}"
    message_text = (
        f"🚀 *New {TOKEN_NAME} Buy Alert!* 🚀\n\n"
        f"A new investor has just joined the AgamaCoin family!\n\n"
        f"💰 *Amount:* {bnb_amount_formatted} BNB\n\n"
        f"Let's give them a warm welcome! 🔥"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ View Transaction on BSCScan", url=f"https://bscscan.com/tx/{tx_hash}")],
        [InlineKeyboardButton("💰 Buy AgamaCoin", url=BSCSCAN_TOKEN_URL)]
    ])
    try:
        await bot.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=TOKEN_LOGO_URL,
            caption=message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        print(f"✅ Alert sent for transaction: {tx_hash}")
    except Exception as e:
        print(f"❌ Failed to send Telegram alert for {tx_hash}. Error: {e}")

# --- Blockchain Monitoring Logic ---
async def handle_transaction(tx, w3, bot):
    """Processes a single transaction to check if it's a valid purchase."""
    try:
        # We only care about transactions sent directly to our contract
        if tx.to and tx.to.lower() == TOKEN_CONTRACT_ADDRESS.lower():
            # Check if the BNB value sent is above our minimum threshold
            if tx.value >= MIN_PURCHASE_WEI:
                # Use the w3 instance to convert from Wei
                bnb_value = w3.from_wei(tx.value, 'ether')
                tx_hash = tx.hash.hex()
                print(f"✔️  Valid purchase detected! Hash: {tx_hash}, Amount: {bnb_value} BNB")
                await send_telegram_alert(bot, bnb_value, tx_hash)
    except Exception as e:
        print(f"⚠️ Could not process transaction {tx.get('hash', 'N/A').hex()}. Error: {e}")

async def process_block(block_hash, w3, bot):
    """Fetches a block by its hash and processes its transactions."""
    try:
        print(f"Processing block: {block_hash.hex()}")
        block = await w3.eth.get_block(block_hash, full_transactions=True)
        # Create a list of tasks to process transactions concurrently
        tasks = [handle_transaction(tx, w3, bot) for tx in block.transactions]
        await asyncio.gather(*tasks)
    except Exception as e:
        print(f"Error processing block {block_hash.hex()}: {e}")

async def main_loop(bot: Bot):
    """The main event loop that listens for new blocks using a filter."""
    print("Connecting to BSC via QuickNode for monitoring...")
    w3 = AsyncWeb3(AsyncWeb3.AsyncWebsocketProvider(QUICKNODE_BSC_URL))
    
    if not await w3.is_connected():
        print("❌ Failed to connect to the BSC node in monitoring loop.")
        return

    print("✅ Successfully connected to BSC. Creating new block filter...")
    # Create a filter to listen for new blocks
    block_filter = await w3.eth.create_filter('latest')
    print("✅ Block filter created. Starting monitor loop...")

    try:
        while True:
            try:
                # Check the filter for new block hashes
                new_blocks = await block_filter.get_new_entries()
                if new_blocks:
                    print(f"Found {len(new_blocks)} new block(s).")
                    # Process each new block concurrently
                    await asyncio.gather(*(process_block(block_hash, w3, bot) for block_hash in new_blocks))
                
                # Wait a short interval before checking the filter again
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                print("Monitoring loop cancelled.")
                break # Exit the loop if cancelled
            except Exception as e:
                print(f"An error occurred in the main loop: {e}. Reconnecting in 15 seconds...")
                await asyncio.sleep(15)
    finally:
        print("Monitoring loop has shut down.")


# --- Main Execution ---
def main():
    """Starts the bot."""
    try:
        validate_config()
        
        print("Initializing Telegram Bot Application...")
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Add handlers for commands and button clicks
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CallbackQueryHandler(button_callback))

        print("Bot is starting... Press Ctrl-C to stop.")
        # Run the bot until the user presses Ctrl-C
        application.run_polling()

    except (ValueError, ConnectionError) as e:
        print(f"CRITICAL ERROR: {e}")
    except KeyboardInterrupt:
        print("\nBot stopped by user.")

if __name__ == "__main__":
    main()
