import asyncio
import os
from web3 import Web3
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
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
MIN_PURCHASE_BNB = 0.025  # The minimum BNB amount to trigger an alert
TOKEN_LOGO_URL = "https://www.agamacoin.com/agama-logo-new.png"
TOKEN_NAME = "AgamaCoin"
BSCSCAN_TOKEN_URL = f"https://bscscan.com/token/{TOKEN_CONTRACT_ADDRESS}"

# Convert the minimum BNB purchase to Wei (1 BNB = 10^18 Wei)
MIN_PURCHASE_WEI = Web3.to_wei(MIN_PURCHASE_BNB, 'ether')

# --- Input Validation ---
def validate_config():
    """Checks if all necessary environment variables are set."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Error: TELEGRAM_BOT_TOKEN is not set. Please add it to your environment variables.")
    if not TELEGRAM_CHAT_ID:
        raise ValueError("Error: TELEGRAM_CHAT_ID is not set. Please add your target Telegram channel/group ID.")
    if not QUICKNODE_BSC_URL or not QUICKNODE_BSC_URL.startswith('wss://'):
        raise ValueError("Error: QUICKNODE_BSC_URL is not set or is invalid. It must be a WebSocket URL (wss://).")
    print("Configuration validated successfully.")

# --- Telegram Bot Function ---
async def send_telegram_alert(bot, bnb_amount, tx_hash):
    """
    Formats and sends a buy alert to the specified Telegram channel.
    """
    bnb_amount_formatted = f"{bnb_amount:.4f}" # Format to 4 decimal places
    
    # Create a nice, readable message
    message_text = (
        f"🚀 *New {TOKEN_NAME} Buy Alert!* 🚀\n\n"
        f"A new investor has just joined the AgamaCoin family!\n\n"
        f"💰 *Amount:* {bnb_amount_formatted} BNB\n\n"
        f"Let's give them a warm welcome! 🔥"
    )

    # Create an inline button that links to the transaction on BSCScan
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ View Transaction on BSCScan", url=f"https://bscscan.com/tx/{tx_hash}")],
        [InlineKeyboardButton("💰 Buy AgamaCoin", url=BSCSCAN_TOKEN_URL)]
    ])

    try:
        # Send a photo with the caption and the inline keyboard
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
async def handle_transaction(tx, web3, bot):
    """
    Processes a single transaction to check if it's a valid purchase.
    """
    try:
        # We only care about transactions sent directly to our contract
        if tx['to'] and tx['to'].lower() == TOKEN_CONTRACT_ADDRESS.lower():
            
            # Check if the BNB value sent is above our minimum threshold
            if tx['value'] >= MIN_PURCHASE_WEI:
                bnb_value = web3.from_wei(tx['value'], 'ether')
                tx_hash = tx['hash'].hex()
                print(f"✔️  Valid purchase detected! Hash: {tx_hash}, Amount: {bnb_value} BNB")
                
                # Send the alert to Telegram
                await send_telegram_alert(bot, bnb_value, tx_hash)

    except Exception as e:
        # This can happen if a transaction is still pending or has an unusual structure
        print(f"⚠️ Could not process transaction {tx.get('hash', 'N/A').hex()}. Error: {e}")


async def main_loop(web3, bot):
    """
    The main event loop that listens for new blocks and processes them.
    """
    print("Starting blockchain monitor...")
    last_processed_block = web3.eth.block_number
    print(f"Starting from block: {last_processed_block}")

    while True:
        try:
            latest_block = web3.eth.block_number
            
            # Process blocks one by one since the last processed block
            while last_processed_block < latest_block:
                block_to_process = last_processed_block + 1
                print(f"Scanning block {block_to_process}...")
                
                block = web3.eth.get_block(block_to_process, full_transactions=True)
                
                # Create a list of tasks to process transactions concurrently
                tasks = [handle_transaction(tx, web3, bot) for tx in block.transactions]
                await asyncio.gather(*tasks)
                
                last_processed_block = block_to_process

            # Wait for a short period before checking for a new block
            await asyncio.sleep(5) # 5-second delay

        except Exception as e:
            print(f"An error occurred in the main loop: {e}. Reconnecting in 15 seconds...")
            await asyncio.sleep(15)


# --- Main Execution ---
if __name__ == "__main__":
    try:
        # 1. Check if the configuration is valid
        validate_config()

        # 2. Initialize Web3 with the QuickNode WebSocket provider
        print("Connecting to BSC via QuickNode...")
        w3 = Web3(Web3.WebsocketProvider(QUICKNODE_BSC_URL))
        if not w3.is_connected():
            raise ConnectionError("Failed to connect to the BSC node.")
        print("✅ Successfully connected to BSC.")

        # 3. Initialize the Telegram Bot
        telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
        print("✅ Telegram Bot initialized.")

        # 4. Start the main monitoring loop
        asyncio.run(main_loop(w3, telegram_bot))

    except (ValueError, ConnectionError) as e:
        print(f"CRITICAL ERROR: {e}")
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
