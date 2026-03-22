#!/bin/bash
# DruidClaw - Installation Script
# Simple wrapper that installs dependencies without starting the server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  DruidClaw - Installation"
echo "========================================"
echo

# Check Python version
echo ">>> Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3.8+ first:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  macOS: brew install python3"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "    Python version: $PYTHON_VERSION"

# Check for pip
echo ">>> Checking pip..."
if ! python3 -m pip --version &> /dev/null; then
    echo "Error: pip is not installed"
    exit 1
fi

# Create virtual environment
echo ">>> Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "    Virtual environment created."
else
    echo "    Virtual environment already exists."
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo ">>> Upgrading pip..."
python -m pip install --upgrade pip -q
echo "    pip upgraded."

# Install dependencies
echo ">>> Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt -q
    echo "    Dependencies installed."
else
    echo "Error: requirements.txt not found"
    exit 1
fi

# Install python-multipart
echo ">>> Installing additional packages..."
pip install python-multipart -q
echo "    Additional packages installed."

echo
echo "========================================"
echo "  DruidClaw 安装完成!"
echo "========================================"
echo
echo "启动服务请运行："
echo "  ./start.sh"
echo
