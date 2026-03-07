#!/bin/bash

# SonarBot - Quick Start Script
# This script helps you get started quickly

echo "🤖 SonarBot - Quick Start"
echo "================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker Desktop first."
    echo "   Visit: https://www.docker.com/products/docker-desktop"
    exit 1
fi

# Check if Docker Compose is available
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available. Please update Docker Desktop."
    exit 1
fi

echo "✅ Docker is installed"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from template..."
    cp .env.example .env
    echo ""
    echo "📝 Please edit the .env file and add your Groq API key:"
    echo "   nano .env"
    echo ""
    echo "   Get your API key from: https://console.groq.com"
    echo ""
    read -p "Press Enter after you've added your API key..."
fi

# Verify GROQ_API_KEY is set
if grep -q "your_groq_api_key_here" .env; then
    echo "❌ Please replace 'your_groq_api_key_here' with your actual Groq API key in .env"
    exit 1
fi

echo "✅ Configuration file found"
echo ""

# Start the application
echo "🚀 Starting SonarBot..."
echo ""

docker compose up --build -d

echo ""
echo "⏳ Waiting for services to start..."
sleep 10

# Check if services are running
if docker compose ps | grep -q "Up"; then
    echo ""
    echo "✅ SonarBot is running!"
    echo ""
    echo "🌐 Access the application:"
    echo "   Frontend:  http://localhost:3000"
    echo "   Backend:   http://localhost:8000"
    echo "   API Docs:  http://localhost:8000/docs"
    echo ""
    echo "📋 Useful commands:"
    echo "   View logs:        docker compose logs -f"
    echo "   Stop services:    docker compose down"
    echo "   Restart:          docker compose restart"
    echo ""
else
    echo "❌ Failed to start services. Check logs:"
    echo "   docker compose logs"
fi