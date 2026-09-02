---
trigger: always_on
description: AI-Inbox Full-Stack loyihasining (Backend + Frontend) to'liq arxitekturasi va ma'lumotlar xaritasi.
---

# Project Context & Blueprint — Social-Commerce AI Inbox

## Overview
**Social-Commerce AI Inbox** — bu Instagram va Telegram platformalari orqali keluvchi mijozlar xabarlarini avtomatlashtiruvchi B2B SaaS platformasi. Google Gemini AI integratsiyasi yordamida do'kon egalariga (Merchants) AI sotuvchi yaratish, mahsulotlar/xizmatlarni taklif etish va avtomatik buyurtmalar/lidlarni qabul qilish imkonini beradi.

## System Repositories
1. **Backend Project**: `/home/asilbek/PycharmProjects/AI-Inbox-backend` (Django 6.1, DRF 3.16, Celery 5.5, Gemini API, PostgreSQL, Redis)
2. **Frontend Project**: `/home/asilbek/PycharmProjects/Ai-Inbox-frontend` (Next.js TWA Dashboard, TypeScript, Bun, TailwindCSS)
3. **Master System Prompt File**: [MASTER_PROMPT.md](file:///home/asilbek/PycharmProjects/AI-Inbox-backend/MASTER_PROMPT.md)

## Core Tech Stack
- **Backend Framework**: Python 3.13+, Django 6.1, Django REST Framework 3.16, SimpleJWT
- **Database**: PostgreSQL (driver: `psycopg3`), Redis (Cache & Task Broker)
- **Async Tasks**: Celery 5.5 + `django-celery-beat` (periodic retention) + `django-celery-results`
- **AI Integration**: Google Gemini API (`google-generativeai`) with multi-tenant system prompt builder, order extractor, moderation
- **Integrations**: Telegram Bot API (`python-telegram-bot`), Instagram Meta Graph API webhooks, `httpx` async client
- **Frontend / TWA**: Next.js static Telegram Mini App dashboard build (`/out`) mounted at `/app/` on Django backend
- **API Docs**: OpenAPI 3 / Swagger UI (`drf-spectacular`) at `/api/v1/docs/`

## Project Structure & Key Directories
```
Backend: /home/asilbek/PycharmProjects/AI-Inbox-backend/
├── ai_inbox_backend/            # Main Django settings, urls, celery, wsgi/asgi
├── apps/
│   ├── api/                     # Central API v1 router (/api/v1/) & Swagger docs
│   ├── stores/                  # Store model (tenant), owner linkage, AI system prompts
│   ├── chat/                    # ChatMessage & BroadcastCampaign models, Gemini AI service, platform senders
│   ├── customers/               # Customer model (auto-synced from Telegram/Instagram)
│   ├── products/                # Product catalog model per store, AI search integration
│   ├── orders/                  # Order & OrderItem models, order statuses, AI auto-creation
│   ├── webhooks/                # Telegram & Instagram webhook views and Celery tasks pipeline
│   ├── core/                    # BaseModel (UUID, timestamps, soft-delete), custom JWT auth, TWA views
│   └── notifications/           # Notification engine
├── MASTER_PROMPT.md             # Master system prompt wrapped into one single file
├── deploy_twa.sh                # TWA build deploy helper from frontend
└── docker-compose.yml           # Postgres + Redis + Django + Celery + Beat setup

Frontend: /home/asilbek/PycharmProjects/Ai-Inbox-frontend/
├── src/                         # Next.js App router (TWA Dashboard UI, Settings, Inbox, Orders)
├── out/                         # Static HTML/JS build copied to Backend static/twa/
├── package.json                 # Next.js, Tailwind, Telegram WebApp SDK dependencies
└── next.config.ts               # Static export configuration (output: 'export')
```

## Key Models Architecture
1. **Store** ([apps/stores/models.py](file:///home/asilbek/PycharmProjects/AI-Inbox-backend/apps/stores/models.py)): Multi-tenant anchor (`owner` 1-to-1 User). Contains `platform`, `category_type` (e_commerce, education, services), `ig_access_token`, `tg_bot_token`, `tg_owner_chat_id`, `ai_system_prompt`, `ai_model`, `ai_active`.
2. **Customer** ([apps/customers/models.py](file:///home/asilbek/PycharmProjects/AI-Inbox-backend/apps/customers/models.py)): End-user profile linked to a `Store` + `platform_user_id`. Tracks `ai_active` (for human handoff).
3. **ChatMessage** ([apps/chat/models.py](file:///home/asilbek/PycharmProjects/AI-Inbox-backend/apps/chat/models.py)): Unique message record (`store`, `message_id`, `platform` unique constraint for idempotency).
4. **Product** ([apps/products/models.py](file:///home/asilbek/PycharmProjects/AI-Inbox-backend/apps/products/models.py)): Product item per `Store` with `price`, `stock`, `metadata`, and AI search helper `search_for_ai`.
5. **Order** ([apps/orders/models.py](file:///home/asilbek/PycharmProjects/AI-Inbox-backend/apps/orders/models.py)): Order record created manually or auto-extracted by AI (`status`: new, confirmed, cancelled, delivered).

## Development Rules
1. **NO MOCK DATA**: Never use hardcoded mock responses or fake data. All endpoints and features interact directly with PostgreSQL/Django ORM and live API endpoints.
2. **Direct Integration**: Frontend/TWA and Backend communicate strictly via real REST JSON APIs.
3. **Idempotency & Resilience**: Always maintain idempotency on incoming platform webhook messages (`message_id` + `store` + `platform`).
