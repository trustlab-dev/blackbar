#!/bin/bash

echo "🔍 BlackBar Prerequisites Check"
echo "================================"
echo ""

ERRORS=0
WARNINGS=0

# Check Docker
echo -n "Checking Docker... "
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version | cut -d ' ' -f3 | cut -d ',' -f1)
    echo "✅ Found ($DOCKER_VERSION)"
else
    echo "❌ Not found"
    echo "   Install: https://docs.docker.com/get-docker/"
    ERRORS=$((ERRORS + 1))
fi

# Check docker compose
echo -n "Checking docker compose... "
if docker compose version &> /dev/null; then
    COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || docker compose version | grep -oP 'v\K[0-9.]+' | head -1)
    echo "✅ Found ($COMPOSE_VERSION)"
else
    echo "❌ Not found"
    echo "   Install Docker with Compose plugin: https://docs.docker.com/compose/install/"
    ERRORS=$((ERRORS + 1))
fi

# Check if Docker daemon is running
echo -n "Checking Docker daemon... "
if docker info &> /dev/null; then
    echo "✅ Running"
else
    echo "❌ Not running"
    echo "   Start Docker Desktop or run: sudo systemctl start docker"
    ERRORS=$((ERRORS + 1))
fi

# Check .env file
echo -n "Checking .env file... "
if [ -f .env ]; then
    echo "✅ Found"
    
    # Check JWT_SECRET
    if grep -q "JWT_SECRET=" .env; then
        JWT_SECRET=$(grep "JWT_SECRET=" .env | cut -d '=' -f2)
        if [ ${#JWT_SECRET} -lt 32 ]; then
            echo "   ⚠️  JWT_SECRET is too short (should be 32+ characters)"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        echo "   ⚠️  JWT_SECRET not set"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "⚠️  Not found (will be created)"
    WARNINGS=$((WARNINGS + 1))
fi

# Check ports
echo -n "Checking port 3000... "
if lsof -Pi :3000 -sTCP:LISTEN -t &> /dev/null; then
    echo "⚠️  In use"
    echo "   Something is already using port 3000"
    WARNINGS=$((WARNINGS + 1))
else
    echo "✅ Available"
fi

echo -n "Checking port 8000... "
if lsof -Pi :8000 -sTCP:LISTEN -t &> /dev/null; then
    echo "⚠️  In use"
    echo "   Something is already using port 8000"
    WARNINGS=$((WARNINGS + 1))
else
    echo "✅ Available"
fi

echo -n "Checking port 27017... "
if lsof -Pi :27017 -sTCP:LISTEN -t &> /dev/null; then
    echo "⚠️  In use"
    echo "   MongoDB might already be running"
    WARNINGS=$((WARNINGS + 1))
else
    echo "✅ Available"
fi

# Check disk space
echo -n "Checking disk space... "
AVAILABLE=$(df -BG . | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE" -gt 5 ]; then
    echo "✅ ${AVAILABLE}GB available"
else
    echo "⚠️  Only ${AVAILABLE}GB available"
    echo "   Recommend at least 5GB free"
    WARNINGS=$((WARNINGS + 1))
fi

# Check for existing containers
echo -n "Checking for existing containers... "
EXISTING=$(docker compose ps -q 2>/dev/null | wc -l)
if [ "$EXISTING" -gt 0 ]; then
    echo "⚠️  Found $EXISTING running container(s)"
    echo "   Run 'docker compose down' to stop them"
    WARNINGS=$((WARNINGS + 1))
else
    echo "✅ None found"
fi

echo ""
echo "================================"
echo "Summary:"
echo "  Errors: $ERRORS"
echo "  Warnings: $WARNINGS"
echo ""

if [ $ERRORS -gt 0 ]; then
    echo "❌ Prerequisites not met. Please fix errors above."
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo "⚠️  Some warnings found. You can proceed but may encounter issues."
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ All prerequisites met! Ready to run setup."
fi

echo ""
echo "Next step: ./setup-multitenant.sh"
