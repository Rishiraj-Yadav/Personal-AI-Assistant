#!/bin/bash

# OpenClaw Desktop Agent - Installation Script
# Installs dependencies for desktop control

echo "=================================================="
echo "🖥️  OpenClaw Desktop Agent - Installation"
echo "=================================================="
echo ""

# Detect OS
OS="$(uname -s)"
echo "Detected OS: $OS"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $PYTHON_VERSION"
echo ""

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt

# Install platform-specific dependencies
if [[ "$OS" == "Linux" ]]; then
    echo ""
    echo "🐧 Linux detected - Installing system dependencies..."
    echo "Note: You may need sudo privileges"
    echo ""
    
    # Detect package manager
    if command -v apt-get &> /dev/null; then
        echo "Using apt-get..."
        sudo apt-get update
        sudo apt-get install -y python3-tk python3-dev scrot
        sudo apt-get install -y tesseract-ocr
        sudo apt-get install -y wmctrl  # For window management
    elif command -v yum &> /dev/null; then
        echo "Using yum..."
        sudo yum install -y python3-tkinter python3-devel
        sudo yum install -y tesseract
    fi
    
elif [[ "$OS" == "Darwin" ]]; then
    echo ""
    echo "🍎 macOS detected - Installing system dependencies..."
    echo ""
    
    # Check if Homebrew is installed
    if ! command -v brew &> /dev/null; then
        echo "❌ Homebrew not found!"
        echo "Please install Homebrew first: https://brew.sh"
        exit 1
    fi
    
    echo "Using Homebrew..."
    brew install tesseract
    
    # macOS-specific Python packages
    pip3 install pyobjc-framework-Quartz pyobjc-framework-ApplicationServices
    
else
    echo "⚠️  Unsupported OS for auto-install: $OS"
    echo "Please install Tesseract OCR manually"
fi

echo ""
echo "=================================================="
echo "✅ Installation Complete!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "1. Review configuration: nano config.py"
echo "2. Start desktop agent: ./start.sh"
echo "3. Check it's running: curl http://localhost:7777/health"
echo ""
echo "⚠️  IMPORTANT SECURITY NOTES:"
echo "- Desktop Agent runs on localhost only (127.0.0.1)"
echo "- API key is auto-generated in config/api_key.txt"
echo "- Safe mode is ENABLED by default"
echo "- Review allowed apps in config.py"
echo ""