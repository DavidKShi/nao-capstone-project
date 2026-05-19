#!/bin/bash

# Capstone 2026 - Robot Startup Script
# This script starts all 4 required services in separate Terminal windows.

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ── Configuration ──────────────────────────────────────────────────────
ROBOT_IP="YOUR_ROBOT_IP"
LAPTOP_IP="YOUR_LAPTOP_IP"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
WEBSOCKET_DIR="$SCRIPT_DIR/websocket"
NAOQI_DIR="$SCRIPT_DIR/naoqi"

VENV="$HOME/nao-capstone-3.11"
NAOQI_SITE_PACKAGES="$HOME/naoqi-site-packages"

# Load API keys from .env file (one directory up from Capstone_2026)
# Format: one key per line, e.g.  OPENAI_API_KEY=sk-...
#                                  AUDD_API_KEY=...
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
    while IFS='=' read -r key value; do
        # skip blank lines and comments
        key="$(echo "$key" | tr -d '[:space:]')"
        [ -z "$key" ] && continue
        [[ "$key" == \#* ]] && continue
        value="$(echo "$value" | tr -d '[:space:]')"
        export "$key=$value"
    done < "$ENV_FILE"
fi

echo -e "${GREEN}=== Capstone 2026 Robot Startup ===${NC}\n"
echo "  Robot IP:  $ROBOT_IP"
echo "  Laptop IP: $LAPTOP_IP"
echo ""

# ── Preflight checks ──────────────────────────────────────────────────

# Check venv exists
if [ ! -f "$VENV/bin/python3.11" ]; then
    echo -e "${RED}ERROR: Python 3.11 venv not found at $VENV${NC}"
    echo "Create it with:  /opt/homebrew/bin/python3.11 -m venv $VENV"
    exit 1
fi

# Check naoqi symlink
if [ ! -d "$NAOQI_SITE_PACKAGES" ]; then
    echo -e "${YELLOW}Creating naoqi site-packages symlink...${NC}"
    ln -sfn "$SCRIPT_DIR/../pynaoqi-installation-for-mac/pynaoqi/lib/python2.7/site-packages" "$NAOQI_SITE_PACKAGES"
fi

# Check API key
if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${YELLOW}WARNING: OPENAI_API_KEY not set!${NC}"
    echo "Set it in $ENV_FILE or export it manually."
    read -p "Do you want to enter it now? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "Enter your OpenAI API key: " api_key
        export OPENAI_API_KEY="$api_key"
        echo -e "${GREEN}API key set for this session${NC}\n"
    else
        echo -e "${RED}Exiting. Please set OPENAI_API_KEY first.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ OpenAI API key is set${NC}"
fi

# Check AudD API key
if [ -z "$AUDD_API_KEY" ]; then
    echo -e "${YELLOW}WARNING: AUDD_API_KEY not set! Song recognition will not work.${NC}"
    echo "Add AUDD_API_KEY=your-key to $ENV_FILE  (free key from https://dashboard.audd.io/)"
else
    echo -e "${GREEN}✓ AudD API key is set${NC}"
fi

echo ""
echo "This script will start 4 services in separate Terminal windows:"
echo "  1. Facial Recognition API  (port 5002)"
echo "  2. GPT Flask API           (port 5001)"
echo "  3. Song Recognition API    (port 5003)"
echo "  4. NAO Robot Main Program  (python2.7)"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# ── Helper: open a new macOS Terminal tab/window and run a command ─────
open_terminal() {
    osascript -e "tell application \"Terminal\" to do script \"cd '$1' && $2\""
}

# ── 1. Facial Recognition API (Python 3.11 venv) ──────────────────────
echo -e "\n${GREEN}Starting Facial Recognition API...${NC}"
open_terminal "$WEBSOCKET_DIR" \
    "export LAPTOP_IP='$LAPTOP_IP' && source '$VENV/bin/activate' && python3.11 facial_recognition_api.py"
sleep 2

# ── 2. GPT Flask API (Python 3.11 venv) ───────────────────────────────
echo -e "${GREEN}Starting GPT Flask API...${NC}"
open_terminal "$WEBSOCKET_DIR" \
    "export OPENAI_API_KEY='$OPENAI_API_KEY' && export LAPTOP_IP='$LAPTOP_IP' && source '$VENV/bin/activate' && python3.11 'flask api.py'"
sleep 2

# ── 3. Song Recognition API (Python 3.11 venv) ────────────────────────
echo -e "${GREEN}Starting Song Recognition API...${NC}"
open_terminal "$WEBSOCKET_DIR" \
    "export LAPTOP_IP='$LAPTOP_IP' && export AUDD_API_KEY='$AUDD_API_KEY' && source '$VENV/bin/activate' && python3.11 tone_analysis_api.py"
sleep 2

# ── 4. NAO Robot Main Program (Python 2.7 + pynaoqi) ──────────────────
echo -e "${GREEN}Starting NAO Robot Main Program...${NC}"
open_terminal "$NAOQI_DIR" \
    "export LAPTOP_IP='$LAPTOP_IP' && export PYTHONPATH='$NAOQI_SITE_PACKAGES:\$PYTHONPATH' && export DYLD_LIBRARY_PATH='$NAOQI_SITE_PACKAGES:\$DYLD_LIBRARY_PATH' && python2.7 nao_main.py"

echo ""
echo -e "${GREEN}✓ All services started!${NC}"
echo ""
echo "You should see 4 new Terminal windows."
echo "Check each one to make sure they started successfully."
echo ""
echo "To stop: press Ctrl+C in each Terminal window."
