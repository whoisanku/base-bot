#!/bin/bash

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Please run setup.sh first."
    exit 1
fi

# Activate the virtual environment
source venv/bin/activate

# Run the token monitor
python base_token_monitor.py

# Note: The virtual environment will remain active after this script completes
# To deactivate it manually, run 'deactivate'