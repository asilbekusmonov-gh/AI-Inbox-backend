#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# AI Inbox — TWA Frontend Deploy Script
# Ishlatish: ./deploy_twa.sh
# Frontend: /home/asilbek/PycharmProjects/Ai-Inbox-frontend
# Backend:  /home/asilbek/PycharmProjects/AI-Inbox-backend
# ═══════════════════════════════════════════════════════════════

set -e

FRONTEND_DIR="/home/asilbek/PycharmProjects/Ai-Inbox-frontend"
BACKEND_DIR="/home/asilbek/PycharmProjects/AI-Inbox-backend"
STATIC_DIR="$BACKEND_DIR/static/twa"
TEMPLATES_DIR="$BACKEND_DIR/templates"

echo "🏗️  Next.js frontend build boshlandi..."
cd "$FRONTEND_DIR"
bun run build

echo ""
echo "📦  Static fayllarni Django'ga ko'chirish..."
rm -rf "$STATIC_DIR"
mkdir -p "$STATIC_DIR"

# Next.js static assetlar
cp -r "$FRONTEND_DIR/out/_next" "$STATIC_DIR/"
cp "$FRONTEND_DIR/out/favicon.ico" "$STATIC_DIR/" 2>/dev/null || true

# index.html ham static/twa/ ichida — view shu yerdan o'qiydi
cp "$FRONTEND_DIR/out/index.html" "$STATIC_DIR/index.html"

echo ""
echo "✅  Deploy muvaffaqiyatli yakunlandi!"
echo "🌐  TWA URL: $(grep PUBLIC_URL $BACKEND_DIR/.env | cut -d= -f2)/app/"
