# AI-Inbox

**AI-powered social-commerce inbox for Telegram & Instagram — a multi-tenant SaaS that lets small businesses sell through chat, automatically.**

AI-Inbox connects a business's Telegram (and soon Instagram) presence to a Gemini-powered AI sales assistant. The AI answers customer questions from the store's real catalog, takes orders, books appointments, and hands off to a human operator when needed — all while the owner manages everything from a Telegram Mini App (TWA) dashboard, without installing anything.

> Backend: Django 6 + DRF. Frontend (TWA dashboard): separate repo, Next.js — see [Frontend](#frontend).

---

## Table of Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project layout](#project-layout)
- [Getting started](#getting-started)
- [Onboarding a store](#onboarding-a-store)
- [Management commands](#management-commands)
- [API](#api)
- [CI/CD](#cicd)
- [Security model](#security-model)
- [Frontend](#frontend)
- [Roadmap](#roadmap)

---

## What it does

A store owner (e-commerce shop, education/course center, or services business — salon, clinic, workshop) connects their Telegram account. From that point on:

- **Customers message the store's bot** and get instant, human-like replies from an AI that only talks about *that store's* real products/courses/services — it never invents prices or details.
- **The AI collects what's needed to close the loop**: name, phone, and (depending on the business type) a delivery address, a trial-lesson time, or a booking slot — then automatically creates an **Order** and notifies the owner on Telegram.
- **The owner runs the whole business from a Telegram Mini App**: catalog, orders, live inbox, AI behavior — no separate app to install, no separate login.
- **A human can take over any conversation** at any time; the AI pauses automatically the moment an operator replies.

### Supported business categories

| Category | What the AI collects | What gets created |
|---|---|---|
| `e_commerce` | name, phone, delivery address, items | Order with delivery details |
| `education` | name, phone, course, preferred trial time | Order (lead) with trial-lesson notes |
| `services` | name, phone, service, specialist, booking time | Order (booking) with appointment notes |

## Architecture

**Single shared bot, many tenants.** Every store uses the *same* Telegram bot (`@Ai_InboxBot`) rather than requiring each business to register and host its own bot. A store is onboarded in seconds and identified by two kinds of deep links:

```
https://t.me/Ai_InboxBot?start=admin_<store-uuid>   → claims store ownership (send only to the real owner)
https://t.me/Ai_InboxBot?start=store_<store-uuid>   → routes a customer into that store's conversation
```

A `CustomerSession` pins a Telegram user to whichever store's link they last clicked, so the AI always knows which business it's representing. Anyone who messages the bot with **no** valid link or session is politely redirected — never silently attached to a random store.

```
Telegram/Instagram  →  webhook (signature-verified)  →  Celery task (async, idempotent)
                                                              │
                                                              ├─ resolve Store (deep-link / session)
                                                              ├─ rate-limit check (per-store + global)
                                                              ├─ Gemini (store-scoped system prompt + catalog)
                                                              ├─ extract & verify order JSON (price re-checked
                                                              │  against the real catalog — AI's word is never
                                                              │  trusted for money)
                                                              ├─ create Order + adjust stock
                                                              └─ reply to customer + notify owner
```

Everything inbound is processed **asynchronously via Celery** — the webhook endpoint only validates, enqueues, and returns `200` immediately, so a slow AI call never blocks Telegram's delivery.

## Tech stack

- **Backend**: Django 6, Django REST Framework, PostgreSQL, Redis
- **Async**: Celery (worker + beat), Redis broker
- **AI**: Google Gemini (`google-generativeai`)
- **Auth**: Telegram `initData` HMAC verification (TWA dashboard) + JWT (`djangorestframework-simplejwt`) for any non-Telegram access
- **Docs**: OpenAPI 3 via `drf-spectacular` (Swagger + Redoc)
- **Infra**: fully Dockerized (`docker-compose`) — Postgres, Redis, Django, Celery worker, Celery beat, nginx
- **Monitoring**: Sentry (optional)
- **Frontend**: Next.js 16 (React 19), static-exported and served by this backend as a Telegram Mini App

## Project layout

```
apps/
  core/          Shared base models, Telegram initData authentication
  stores/        Store (tenant) model, onboarding & admin management commands
  customers/     Customer + CustomerSession (deep-link → store routing)
  products/      Catalog (products / courses / services), AI-facing search
  orders/        Order model, stock deduction/restock
  chat/          ChatMessage, Gemini integration, order extraction, rate limiting
  webhooks/      Telegram & Instagram webhook receivers + Celery tasks
  api/           API v1 URL routing, OpenAPI schema
  notifications/ (reserved)
static/twa/      Built frontend (Next.js static export) served at /app/
```

## Getting started

Everything runs in Docker — you don't need Python or Postgres installed locally.

```bash
git clone <this-repo>
cd AI-Inbox-backend
cp .env.example .env   # fill in SECRET_KEY, GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, etc.
docker compose up -d
docker compose exec web python manage.py migrate
```

The API is now available at `http://localhost/api/v1/`, docs at `http://localhost/api/v1/docs/`, and the TWA dashboard at `http://localhost/app/`.

### Exposing it to real Telegram

Telegram needs a public HTTPS URL to deliver webhooks. For local development, a quick tunnel works:

```bash
cloudflared tunnel --url http://localhost:80
```

Then point `.env`'s `PUBLIC_URL` at the tunnel URL, restart `web`, and register the webhook:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<your-tunnel>/webhook/telegram/<TELEGRAM_BOT_TOKEN>/" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

> ⚠️ A quick tunnel is fine for testing but has no uptime guarantee and its URL changes every restart. Before relying on this for real customers, move to a stable domain + server.

### After recreating the `web` container

The reverse proxy (`nginx`) caches the `web` container's resolved IP. If you see `502` errors after `docker compose up -d web`, restart the proxy too:

```bash
docker compose restart nginx
```

## Onboarding a store

```bash
# 1. Create the store and get both links in one step
docker compose exec web python manage.py create_store --name "Zulfiya Fashion" --category e_commerce

# 2. Send the 👑 admin link to the business owner (claims ownership)
# 3. Give the 🛍️ customer link to marketing (Instagram bio, ads, WhatsApp, etc.)
```

The owner opens the admin link once, taps Start, and their Telegram account is bound to that store — the TWA dashboard opens automatically from then on via the bot's menu button.

## Management commands

| Command | Purpose |
|---|---|
| `create_store --name NAME --category {e_commerce,education,services}` | Onboard a new tenant, print both links |
| `get_admin_link --store NAME_OR_UUID` | Re-print a store's admin/customer links |
| `list_stores [--name NAME]` | List all stores with UUID, owner status, product/order counts |
| `revoke_store_owner --store NAME_OR_UUID` | Unbind the current owner (e.g. to hand off to a new account) |
| `set_store_access --store NAME_OR_UUID --active {true,false}` | Suspend/reactivate a store's TWA + bot (e.g. trial expired), data preserved |
| `reset_test_customer --store NAME --username U` | ⚠️ Hard-delete a test customer + their messages/orders, for clean re-testing |
| `seed_demo_data` / `seed_products` | Seed sample data for local development |

All commands include duplicate-name safety: if a name matches more than one store, they refuse to guess and list the candidates with their UUIDs instead.

## API

Interactive docs (Swagger + Redoc) are generated automatically from the codebase:

- `GET /api/v1/docs/` — Swagger UI
- `GET /api/v1/redoc/` — Redoc
- `GET /api/v1/schema/` — raw OpenAPI 3 schema

Every business-data endpoint (`/orders/`, `/products/`, `/customers/`, `/chat/`, `/store/`) is tenant-scoped: a request is resolved to exactly one Store via either a verified Telegram `initData` header or a JWT-authenticated user's own store — there is no way to read or write another tenant's data by passing an ID.

## CI/CD

**CI (`.github/workflows/ci.yml`)** runs on every push/PR to `main` and is active by default — no setup needed:
- Django system check + `makemigrations --check` (catches a model change that's missing its migration before it reaches `main`)
- Migrations applied end-to-end against a throwaway Postgres to confirm they run cleanly
- Docker image build, to catch a broken `Dockerfile`/dependency before it's needed on a real server

**CD (`.github/workflows/deploy.yml`)** is a ready-to-use template, currently `workflow_dispatch`-only (manual trigger) since there's no production server yet. To activate once you have one:
1. Add repo secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH` (the project's absolute path on the server).
2. Uncomment the `push: branches: [main]` trigger in the workflow file.

It then SSHes in, pulls, rebuilds `web`/`celery_worker`/`celery_beat`, restarts the proxy layer (`nginx` — required after any `web` rebuild, since it caches the old container IP), and runs migrations. The [frontend repo](#frontend) has a matching `deploy.yml` that builds the TWA and rsyncs it into this repo's `static/twa/` on the same server — it expects the *same* `DEPLOY_PATH` value.

## Security model

A few things worth knowing if you're extending this codebase:

- **Multi-tenant isolation is enforced at the auth layer**, not per-view — `get_store_from_request()` is the single source of truth for "which store is this request allowed to touch," and every viewset filters through it.
- **The AI is never trusted with money or contact data at face value.** Before an Order is created, item prices are re-verified against the live catalog (never the price Gemini said), and phone numbers are format-checked — mismatches are flagged in the order notes rather than silently accepted.
- **The AI is given the real current date** on every turn specifically so it can catch and reject a customer requesting an already-past date/time, rather than confirming it blindly.
- **JSON leakage is prevented structurally**: the moment the AI's reply shows any sign of its internal order-JSON block, everything from that point onward is cut before the customer ever sees it, regardless of whether the JSON itself is well-formed.
- **A single shared bot token means "which store handles this message" must always come from a verified deep-link or session** — never from a `.first()`/most-recently-updated fallback, which would silently leak one tenant's context to another tenant's customer.
- **Webhook signatures fail closed.** If a signing secret is missing in production, the webhook rejects the request rather than accepting it unverified.

## Frontend

The Telegram Mini App dashboard is a separate Next.js repo, statically exported and copied into `static/twa/` (served at `/app/`). See that repo's README for its own setup. After building it:

```bash
cp -r <frontend-repo>/out/* static/twa/
docker compose restart nginx
```

## Roadmap

- [x] Telegram-first MVP: multi-tenant AI sales chat, TWA dashboard, order/booking pipeline
- [ ] Instagram DM integration (webhook code exists; needs Meta App Review + a stable production domain)
- [ ] Payment integration (Payme/Click) — subscription plan fields already exist on `Store`, not yet enforced
- [ ] Broadcast delivery-rate monitoring (auto-throttle a store whose messages are getting blocked)
- [ ] WhatsApp Business channel

---

*Billing is deliberately deferred until the core chat/ordering experience is validated with real businesses — this is a sequencing choice, not an oversight.*
