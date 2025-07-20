#!/usr/bin/env python3
"""
Base Chain Token Transfer Monitor
This script monitors token transfers to a specific address on the Base blockchain
using the BaseScan API's event logs endpoint.
"""

import requests
import time
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from web3 import Web3
from uniswap_v4_trader import UniswapV4Trader

# Get the absolute path to the .env file
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')

# Load environment variables from .env file
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    print("Warning: .env file not found. Please ensure it exists.")

# Configuration
API_KEY = os.getenv("BASESCAN_API_KEY")
if not API_KEY:
    print("Error: BASESCAN_API_KEY not found in environment.")
    exit(1)

# Base RPC configuration
RPC_URL = "https://mainnet.base.org"
CHAIN_ID = 8453  # Base Mainnet
POLLING_INTERVAL = 2  # Polling interval in seconds
TARGET_ADDRESS = "0xA3296bAEB33c2D5dF1AB417E1a805Dd63D8C3BE3".lower()
ETH_TO_SPEND = 0.00001  # Amount of ETH to spend on the new token

# ERC20 Transfer event signature
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
MIN_TOKEN_AMOUNT = 10_000_000 * (10 ** 18)  # 10M tokens (assuming 18 decimals)

class BaseTokenMonitor:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.session = requests.Session()
        self.last_block = self._load_last_block()
        # Initialize Web3 with Base RPC
        self.web3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not self.web3.is_connected():
            raise ConnectionError("Failed to connect to Base RPC")
        # Initialize the trader
        try:
            self.trader = UniswapV4Trader()
        except Exception as e:
            print(f"Error initializing UniswapV4Trader: {e}")
            print("Please ensure your .env file is set up correctly with PRIVATE_KEY and SMART_WALLET_ADDRESS.")
            exit(1)

    def _make_rpc_request(self, method, params=None):
        """Helper function to make JSON-RPC requests with retries and error handling."""
        max_retries = 3
        retry_delay = 1  # seconds
        
        if params is None:
            params = []
            
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        for attempt in range(max_retries):
            try:
                # Add a small delay to avoid rate limiting
                time.sleep(0.2)
                
                # Make the request
                response = self.session.post(
                    RPC_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
                response.raise_for_status()
                
                data = response.json()
                
                # Check for RPC errors
                if "error" in data:
                    error_msg = data.get("error", {}).get("message", "Unknown RPC error")
                    print(f"RPC Error: {error_msg}")
                    if "rate limit" in error_msg.lower() and attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    return None
                
                return data.get("result")
                
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    print(f"HTTP Request failed after {max_retries} attempts: {e}")
                    return None
                time.sleep(retry_delay * (attempt + 1))
                
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                return None

    def get_latest_block(self):
        """Get the latest block number from the Base chain."""
        result = self._make_rpc_request("eth_blockNumber")
        return int(result, 16) if result else None

    def _load_last_block(self):
        """Load the last processed block number from a file."""
        try:
            with open("last_block.txt", "r") as f:
                block_num = int(f.read().strip())
                print(f"Resuming from saved block: {block_num}")
                return block_num
        except (FileNotFoundError, ValueError):
            print("No saved block found. Starting with the latest block.")
            return self.get_latest_block() or 0

    def _save_last_block(self, block_number):
        """Save the last processed block number to a file."""
        with open("last_block.txt", "w") as f:
            f.write(str(block_number))

    def get_token_transfer_logs(self, from_block, to_block):
        """
        Get ERC20 transfer logs for the target address using eth_getLogs.
        """
        # Create filter parameters
        filter_params = {
            "fromBlock": hex(from_block) if isinstance(from_block, int) else from_block,
            "toBlock": hex(to_block) if isinstance(to_block, int) else to_block,
            "topics": [
                ERC20_TRANSFER_TOPIC,
                None,  # From address (any)
                "0x" + "0" * 24 + TARGET_ADDRESS[2:],  # To address (our target)
            ]
        }
        
        logs = self._make_rpc_request("eth_getLogs", [filter_params]) or []
        return [log for log in logs if self._is_valid_transfer(log)]
    
    def _is_valid_transfer(self, log):
        """Check if the transfer log meets our criteria."""
        try:
            # Check if the transfer is to our target address (topic1 is 'to' address)
            if len(log['topics']) < 3:
                return False
                
            # Get the transfer amount from the data field
            if not log.get('data') or log['data'] == '0x':
                return False
                
            # Convert hex amount to integer
            amount_hex = log['data'].replace('0x', '')
            amount = int(amount_hex, 16)
            
            # Store the token address for later use
            self.last_token_address = log.get('address')
            
            # Check if amount is at least 10M tokens (adjust for token decimals if needed)
            return amount >= MIN_TOKEN_AMOUNT
            
        except Exception as e:
            print(f"Error validating transfer: {e}")
            return False

    def _process_transfer_log(self, log):
        """Format a transfer log, print it, and trigger the buy function."""
        try:
            # Extract transfer details
            block_number = int(log.get('blockNumber', '0x0'), 16)
            tx_hash = log.get('transactionHash', '0x')
            token_address = log.get('address', '0x')
            
            # Parse topics (from, to)
            topics = log.get('topics', [])
            from_address = '0x' + topics[1][-40:] if len(topics) > 1 else '0x0'
            to_address = '0x' + topics[2][-40:] if len(topics) > 2 else '0x0'
            
            # Parse amount from data
            amount = 0
            if log.get('data') and log['data'] != '0x':
                amount = int(log['data'].replace('0x', ''), 16)
            
            # Format and print the output
            output = [
                "\n" + "=" * 80,
                f"  🚨 LARGE TOKEN TRANSFER DETECTED 🚨",
                "  " + "-" * 76,
                f"  Block: {block_number}",
                f"  TX Hash: {tx_hash}",
                f"  Token: {token_address}",
                f"  From: {from_address}",
                f"  To: {to_address}",
                f"  Amount: {amount:,} (raw)",
                "=" * 80 + "\n"
            ]
            print("\n".join(output))

            # --- Trigger the token purchase ---
            print(f"\n>>> Initiating purchase of token {token_address}...\n")
            self.trader.buy_token(token_address, ETH_TO_SPEND)

        except Exception as e:
            print(f"Error processing transfer log: {e}")

    def run(self):
        """Main monitoring loop."""
        print("Starting Base Token Monitor...")
        while True:
            try:
                latest_block = self.get_latest_block()
                if latest_block is None:
                    time.sleep(POLLING_INTERVAL)
                    continue

                # To avoid requesting too many blocks at once on the first run
                if latest_block > self.last_block + 1000:
                    self.last_block = latest_block - 1000

                if self.last_block < latest_block:
                    print(f"Scanning blocks from {self.last_block + 1} to {latest_block}...")
                    logs = self.get_token_transfer_logs(self.last_block + 1, latest_block)
                    
                    if logs:
                        for log in logs:
                            self._process_transfer_log(log)
                    
                    self.last_block = latest_block
                    self._save_last_block(self.last_block)
                
                time.sleep(POLLING_INTERVAL)

            except KeyboardInterrupt:
                print("\nShutting down monitor.")
                break
            except Exception as e:
                print(f"An error occurred in the main loop: {e}")
                time.sleep(10) # Wait longer after an error


if __name__ == "__main__":
    monitor = BaseTokenMonitor(api_key=API_KEY)
    monitor.run()

    def monitor_transfers(self):
        """Continuously monitor for new blocks and parse token transfers."""
        print("🚀 Starting Base Chain Token Transfer Monitor...")
        print(f"🎯 Monitoring address: {TARGET_ADDRESS}")
        print(f"📊 Minimum amount: {MIN_TOKEN_AMOUNT:,} (raw)")
        print(f"⏱️  Polling interval: {POLLING_INTERVAL} second(s)")
        print("-" * 80)
        # Initialize last_block if not set
        if self.last_block is None:
            self.last_block = self.get_latest_block() or 0
            print(f"🔍 Starting from block: {self.last_block}")
        else:
            print(f"🔍 Resuming from block: {self.last_block}")

        print("✅ Monitoring started. Press Ctrl+C to exit.")
        print("-" * 80)

        while True:
            try:
                # Get the latest block
                latest_block = self.get_latest_block()
                if not latest_block:
                    print("⚠️  Could not fetch latest block. Retrying...")
                    time.sleep(POLLING_INTERVAL)
                    continue

                # Process new blocks if any
                if latest_block > self.last_block:
                    print(f"\n🔍 Checking blocks {self.last_block + 1} to {latest_block}...")
                    
                    # Get all transfer logs in this block range
                    logs = self.get_token_transfer_logs(self.last_block + 1, latest_block)
                    
                    if logs:
                        print(f"🎯 Found {len(logs)} relevant transfer(s)")
                        for log in logs:
                            print(self._format_transfer_log(log))
                    else:
                        print(f"ℹ️  No large transfers found in blocks {self.last_block + 1} to {latest_block}")
                    
                    # Update the last processed block
                    self.last_block = latest_block
                    self._save_last_block(self.last_block)
                
                # Wait before next poll
                time.sleep(POLLING_INTERVAL)

            except KeyboardInterrupt:
                print("\n👋 Exiting monitor...")
                break
                
            except Exception as e:
                print(f"\n⚠️  An error occurred: {e}")
                print("🔄 Retrying...")
                time.sleep(POLLING_INTERVAL)

if __name__ == "__main__":
    if not API_KEY:
        print("API key is missing. Exiting.")
    else:
        monitor = BaseTokenMonitor(API_KEY)
        monitor.monitor_transfers()