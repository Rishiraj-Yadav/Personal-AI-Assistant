# OpenClaw Desktop Agent - Startup Script

Write-Host "Starting Desktop Agent Service..."
Write-Host ""

# Create necessary directories
if (!(Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

if (!(Test-Path "config")) {
    New-Item -ItemType Directory -Path "config" | Out-Null
}

# Generate API key if it doesn't exist
if (!(Test-Path "config/api_key.txt")) {
    Write-Host "Generating API key..."
    python config.py
}

# Check if running in safe mode
try {
    $safeModeCheck = Select-String -Path "config.py" -Pattern "SAFE_MODE.*=.*True" -ErrorAction SilentlyContinue
    
    if ($null -ne $safeModeCheck) {
        Write-Host "Safe Mode: ENABLED"
    }
    else {
        Write-Host "WARNING: Safe Mode: DISABLED - Agent will control your computer!"
    }
}
catch {
    Write-Host "WARNING: Could not verify Safe Mode setting."
}

Write-Host ""
Write-Host "Starting service on http://localhost:7777"
Write-Host "Press Ctrl+C to stop"
Write-Host ""

# Start the service
python desktop_agent.py










# #!/bin/bash

# # OpenClaw Desktop Agent - Startup Script

# echo "🖥️  Starting Desktop Agent Service..."
# echo ""

# # Create necessary directories
# mkdir -p logs
# mkdir -p config

# # Generate API key if it doesn't exist
# if [ ! -f "config/api_key.txt" ]; then
#     echo "Generating API key..."
#     python3 config.py
# fi

# # Check if running in safe mode
# if grep -q "SAFE_MODE.*=.*True" config.py 2>/dev/null; then
#     echo "✓ Safe Mode: ENABLED"
# else
#     echo "⚠️  Safe Mode: DISABLED - Agent will control your computer!"
# fi

# echo ""
# echo "Starting service on http://localhost:7777"
# echo "Press Ctrl+C to stop"
# echo ""

# # Start the service
# python3 desktop_agent.py