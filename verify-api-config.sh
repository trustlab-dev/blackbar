#!/bin/bash
# Verification script to check API configuration

echo "🔍 BlackBar API Configuration Verification"
echo "==========================================="
echo ""

echo "1. Checking git status..."
git status

echo ""
echo "2. Checking current branch..."
git branch --show-current

echo ""
echo "3. Checking api.ts content..."
echo "   Looking for baseURL configuration:"
grep -A 2 "baseURL" frontend/src/api.ts

echo ""
echo "4. Checking api/index.ts content..."
echo "   Looking for baseURL configuration:"
grep -A 2 "baseURL" frontend/src/api/index.ts

echo ""
echo "5. Checking running containers..."
docker compose ps

echo ""
echo "6. Checking frontend container logs (last 20 lines)..."
docker compose logs --tail=20 frontend

echo ""
echo "7. Testing API endpoint from within container..."
docker compose exec frontend wget -O- http://backend:8000/health 2>/dev/null || echo "Backend not accessible"

echo ""
echo "✅ Verification complete!"
echo ""
echo "Expected baseURL values:"
echo "  - frontend/src/api.ts should have: baseURL: \"/api\""
echo "  - frontend/src/api/index.ts should have: baseURL: '/api'"
echo ""
echo "If these don't match, run:"
echo "  git pull origin JURISDICTIONS-1"
echo "  docker compose down"
echo "  docker compose build --no-cache"
echo "  docker compose up -d"
