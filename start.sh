#!/bin/bash
# DruidClaw - Smart Startup Script
# Auto-detects installation status and guides user through setup
# Usage: ./start.sh [--host 0.0.0.0] [--port 19123] [--passwd your_password]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "========================================"
echo "  🐻 DruidClaw - Claude Code OS Shell"
echo "========================================"
echo -e "${NC}"

# Check if already installed - FAST check using marker file
check_installed() {
    # Fast path: check marker file first
    [ -f "$SCRIPT_DIR/.installed" ] && return 0

    # Check Python venv exists
    [ ! -x "$SCRIPT_DIR/venv/bin/python3" ] && return 1

    # Quick check: verify druidclaw package exists
    [ ! -d "$SCRIPT_DIR/venv/lib/"*"/site-packages/druidclaw" ] && \
    [ ! -d "$SCRIPT_DIR/venv/lib/"*"/dist-packages/druidclaw" ] && return 1

    return 0
}

# Install function
do_install() {
    echo -e "${YELLOW}>>> 开始安装 DruidClaw...${NC}"
    echo

    # Check Python version
    echo ">>> Checking Python version..."
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Error: Python 3 is not installed${NC}"
        echo "Please install Python 3.8+ first:"
        echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
        echo "  macOS: brew install python3"
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    echo -e "    ${GREEN}Python version: $PYTHON_VERSION${NC}"

    # Check for pip
    echo ">>> Checking pip..."
    if ! python3 -m pip --version &> /dev/null; then
        echo -e "${RED}Error: pip is not installed${NC}"
        exit 1
    fi
    echo -e "    ${GREEN}pip is available${NC}"

    # Create virtual environment
    echo ">>> Creating virtual environment..."
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        echo -e "    ${GREEN}Virtual environment created${NC}"
    else
        echo -e "    ${GREEN}Virtual environment already exists${NC}"
    fi

    # Activate virtual environment
    source venv/bin/activate

    # Upgrade pip
    echo ">>> Upgrading pip..."
    python -m pip install --upgrade pip -q
    echo -e "    ${GREEN}pip upgraded${NC}"

    # Install dependencies
    echo ">>> Installing Python dependencies..."
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt -q
        echo -e "    ${GREEN}Dependencies installed${NC}"
    else
        echo -e "${RED}Error: requirements.txt not found${NC}"
        exit 1
    fi

    # Install python-multipart
    echo ">>> Installing additional packages..."
    pip install python-multipart -q
    echo -e "    ${GREEN}Additional packages installed${NC}"

    echo
    echo -e "${GREEN}========================================"
    echo "  ✅ DruidClaw 安装完成!"
    echo -e "========================================${NC}"
    echo
    # Mark as installed
    touch "$SCRIPT_DIR/.installed"
}

# Main logic
# Allow skipping install check via environment variable (set after first successful install)
if [ -f "$SCRIPT_DIR/.installed" ]; then
    # Already installed, skip check and start directly
    exec "$SCRIPT_DIR/venv/bin/python3" -m druidclaw.web "$@"
elif check_installed; then
    # First time: mark as installed
    touch "$SCRIPT_DIR/.installed"
    echo -e "${GREEN}>>> 检测到 DruidClaw 已安装，正在启动...${NC}"
    echo
    exec "$SCRIPT_DIR/venv/bin/python3" -m druidclaw.web "$@"
else
    echo -e "${YELLOW}>>> 首次运行检测，DruidClaw 尚未安装${NC}"
    echo
    read -p "是否现在安装？[Y/n] " choice
    case "$choice" in
        y|Y|"") do_install ;;
        n|N)
            echo "退出安装。运行 ./install.sh 可手动安装"
            exit 0
            ;;
        *)
            echo "无效选择，退出"
            exit 1
            ;;
    esac

    # Mark as installed
    touch "$SCRIPT_DIR/.installed"

    echo -e "${GREEN}>>> 安装完成，正在启动 DruidClaw...${NC}"
    echo
    exec "$SCRIPT_DIR/venv/bin/python3" -m druidclaw.web "$@"
fi
