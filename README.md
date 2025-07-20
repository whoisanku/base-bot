# Base Chain Token Tools

A collection of Python tools for interacting with tokens on the Base blockchain (Chain ID: 8453).

## Features

1. **Token Transfer Monitor**

   - Continuously monitors the latest blocks on Base chain
   - Fetches token transfer events for each new block
   - Displays detailed information about each transfer:
     - Transaction hash
     - From/To addresses
     - Token name and symbol
     - Transfer amount (properly formatted with decimals)
     - Timestamp

2. **Token Swapper**
   - Buy tokens with ETH on Uniswap V3
   - Sell tokens for ETH on Uniswap V3
   - Automatic fee tier detection
   - Real-time transaction execution

## Setup Instructions

### Prerequisites

- Python 3.8 or higher
- A Base-compatible wallet with ETH for gas fees
- macOS (instructions are tailored for macOS)

### Installation

1. Clone or download this repository

2. Run the setup script to create a virtual environment and install dependencies:

```bash
./setup.sh
```

This will:

- Create a Python virtual environment
- Activate the virtual environment
- Install all required dependencies

### Running the Monitor

To run the token transfer monitor:

```bash
./run.sh
```

Or manually:

```bash
# Activate the virtual environment
source venv/bin/activate

# Run the monitor
python base_token_monitor.py

# When done, deactivate the virtual environment
deactivate
```

## Configuration

The monitor is configured with the following default settings:

- API Key: `YOUR API KEY`
- Base API URL: `https://api.basescan.org/api`
- Chain ID: `8453` (Base Mainnet)
- Polling Interval: `1 second`

You can modify these settings in the `base_token_monitor.py` file if needed.

## Notes

- The Etherscan API has rate limits. If you encounter issues with too many requests, try increasing the polling interval.
- Press `Ctrl+C` to stop the monitor at any time.
