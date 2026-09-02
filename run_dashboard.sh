#!/bin/bash
# NE India Red Zone Platform — Dashboard Startup
# Usage: bash run_dashboard.sh

echo "🚀 Starting NE India Red Zone Platform..."
echo ""

# Check dependencies
pip install fastapi uvicorn 2>/dev/null

echo "📊 Starting API server on http://localhost:8000"
echo "🗺️  Open http://localhost:8000 in your browser"
echo ""
echo "Press Ctrl+C to stop"
echo "========================================="

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
