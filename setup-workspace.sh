#!/bin/bash

# OpenClaw Agent - Workspace Setup Helper
# This script helps you configure where files are created

echo "🗂️  OpenClaw Agent - Workspace Configuration"
echo "=============================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "✅ Created .env file"
    echo ""
fi

# Show current workspace path
CURRENT_PATH=$(grep WORKSPACE_PATH .env | cut -d'=' -f2)
if [ -z "$CURRENT_PATH" ]; then
    CURRENT_PATH="./workspace (default)"
fi

echo "📍 Current workspace path: $CURRENT_PATH"
echo ""
echo "Choose an option:"
echo ""
echo "1) Use default (./workspace in project folder)"
echo "2) Use Documents folder"
echo "3) Use Desktop"
echo "4) Enter custom path"
echo "5) Keep current and exit"
echo ""
read -p "Select option (1-5): " choice

case $choice in
    1)
        WORKSPACE_PATH="./workspace"
        ;;
    2)
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            WORKSPACE_PATH="$HOME/Documents/agent-workspace"
        elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
            # Windows
            WORKSPACE_PATH="C:/Users/$USERNAME/Documents/agent-workspace"
        else
            # Linux
            WORKSPACE_PATH="$HOME/Documents/agent-workspace"
        fi
        ;;
    3)
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            WORKSPACE_PATH="$HOME/Desktop/agent-workspace"
        elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
            # Windows
            WORKSPACE_PATH="C:/Users/$USERNAME/Desktop/agent-workspace"
        else
            # Linux
            WORKSPACE_PATH="$HOME/Desktop/agent-workspace"
        fi
        ;;
    4)
        echo ""
        read -p "Enter full path to workspace folder: " WORKSPACE_PATH
        ;;
    5)
        echo "✅ Keeping current configuration"
        exit 0
        ;;
    *)
        echo "❌ Invalid option"
        exit 1
        ;;
esac

# Convert to forward slashes for cross-platform compatibility
WORKSPACE_PATH=$(echo $WORKSPACE_PATH | sed 's/\\/\//g')

# Create folder if it doesn't exist
if [ ! -d "$WORKSPACE_PATH" ]; then
    mkdir -p "$WORKSPACE_PATH"
    echo "✅ Created folder: $WORKSPACE_PATH"
fi

# Update .env file
if grep -q "WORKSPACE_PATH=" .env; then
    # Update existing line
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|WORKSPACE_PATH=.*|WORKSPACE_PATH=$WORKSPACE_PATH|" .env
    else
        sed -i "s|WORKSPACE_PATH=.*|WORKSPACE_PATH=$WORKSPACE_PATH|" .env
    fi
else
    # Add new line
    echo "WORKSPACE_PATH=$WORKSPACE_PATH" >> .env
fi

echo ""
echo "✅ Workspace configured!"
echo "📁 Location: $WORKSPACE_PATH"
echo ""
echo "Next steps:"
echo "1. Restart Docker: docker-compose down && docker-compose up -d"
echo "2. Create a file via chat: 'Create a file called test.txt'"
echo "3. Check your folder: $WORKSPACE_PATH"
echo ""
echo "📚 For more info, see LOCAL_WORKSPACE_SETUP.md"