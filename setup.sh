#!/bin/bash

# Create a virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate the virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "Installing requirements..."
pip install -r requirements.txt

echo ""
echo "Setup complete! Virtual environment is now ready."
echo ""
echo "To activate the virtual environment in the future, run:"
echo "source venv/bin/activate"
echo ""
echo "To run the token monitor, make sure the virtual environment is activated, then run:"
echo "python base_token_monitor.py"
echo ""
echo "To deactivate the virtual environment when you're done, simply run:"
echo "deactivate"