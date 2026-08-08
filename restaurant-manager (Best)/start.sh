#!/bin/bash

echo "=========================================="
echo "  RESTAURANT MANAGER - Starting..."
echo "=========================================="
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 is not installed!"
    echo "Please install Python from https://python.org"
    exit 1
fi

# Install required packages
echo "Installing required packages..."
pip3 install -r requirements.txt

# Start the application
echo ""
echo "Starting Restaurant Manager..."
echo "Open your browser and go to: http://127.0.0.1:5000"
echo ""
echo "Press CTRL+C to stop the server"
echo "=========================================="
python3 app.py
