# LeadNode

**AI-powered lead generation for Telegram — a multi-tenant SaaS that turns chat traffic into qualified leads for education centers and service businesses.**

LeadNode connects a business's Telegram bot (and group) to a Gemini-powered assistant whose single job is to **capture the customer's name and phone number and hand them to a human specialist**. The owner manages everything from a Telegram Mini App (TWA) dashboard — live inbox, catalog, leads, CRM/Excel export — without installing anything.

> Backend: Django 6 + DRF. Frontend (TWA dashboard): separate repo, Next.js — see [Frontend](#frontend).

---

## Table of Contents

- [What it does](#what-it-does)
- [The core principle](#the-core-principle)
- [Conversation flow](#conversation-flow)
- [Group behavior](#group-behavior)
- [Architecture](#architecture)
- [Safety layers](#safety-layers)
- [Tech stack](#tech-stack)
- [Project layout](#project-layout)
- [Getting started](#getting-started)
- [Onboarding a store](#onboarding-a-store)
- [Super Admin panel](#super-admin-panel)
- [Management commands](#management-commands)
- [API](#api)
- [Testing](#testing)
- [Production deployment](#production-deployment)
- [CI/CD](#cicd)
- [Frontend](#frontend)
- [Roadmap](#roadmap)

---

## What it does

A training center or service business connects its Telegram bot. From that point on:

- **Customers message the bot** and get short, natural replies grounded in *that store's* real catalog — the AI never invents prices, dates or features.
- **The AI's goal is contact capture, not consultation.** It confirms what the customer is interested in, then asks for name + phone so a human specialist can follow up.
- **Valid leads land in the owner's dashboard** and are pushed to Bitrix24 / Google Sheets (if configured), with Excel export always available.
- **A human can take over any conversation** at any time; the AI pauses the moment an operator steps in or the customer asks for a person.

| Category | What the AI collects | What gets created |
|---|---|---|
| `education` | name, phone, course of interest | `Lead` + owner notification |
| `services` | name, phone, service of interest | `Lead` + owner notification |

> **Note:** this project started as a general-purpose chat-commerce inbox with orders, stock and delivery. It was deliberately narrowed to **lead generation only** — there is no order/cart/stock pipeline anymore. `apps/orders/` now contains a single `Lead` model.

## The core principle

> The bot is **not** a salesperson, **not** a consultant, and **not** a teacher. It captures contact details and hands over to a human.

Three rules follow from that, and most of the codebase exists to enforce them:

1. **Contact first.** Any specific question (price, duration, schedule, discount) is answered with a contact offer — *not* with the number itself.
2. **Only an explicit refusal unlocks the details.** If the customer clearly declines ("no, tell me here"), the bot sends the course's **stored full description** verbatim — never a summary the model wrote.
3. **Never teach.** After that description is sent, follow-up questions about course content get redirected back to contact capture rather than an explanation.

**These rules are enforced in code, not only in the prompt.** The prompt describes the behavior; deterministic guards in `apps/chat/ai_service.py` verify it afterwards and rewrite the reply when the model deviates. This is intentional — live testing repeatedly showed prompt-only rules being violated.

## Conversation flow

```
greeting
   ↓
at most ONE clarifying question
   ↓
contact request  ←── regardless of what was asked
   ↓
customer explicitly declines ("yo'q, shu yerda ayting")
   ↓
full stored course text, sent verbatim from Product.full_info   (once per conversation)
   ↓
further content questions → redirected back to contact capture
   ↓
name + phone → validated → Lead → owner notified → human takes over
```

Deterministic guards along that path:

| Guard | What it prevents |
|---|---|
| `_scrub_private_facts_before_contact` | Any price/duration/schedule number leaking before contact is captured |
| `_customer_declined_contact` | Treating a repeated question or an objection as a refusal |
| `_build_full_info_response` | Sending the course script without a real refusal, or sending it twice |
| `_redirect_to_contact_after_script` | The bot turning into a tutor after the script was sent |
| `_ensure_contact_ask` | The conversation looping in clarifying questions |
| `_normalize_phone` / `_validate_full_name` | Unreachable contacts (`"ali 987654"`, an extra digit) becoming leads |
| "registered" stage gating | Marking a customer as converted when no `Lead` row was actually written |

Each of these exists because of a specific bug found in live testing; the regression tests name the date and the exact failing conversation.

**Follow-ups.** A customer who goes quiet without leaving contact gets one reminder after ~6h and another ~18h later (`Store.follow_up_delay_1_hours` / `_2_hours`), unless they already declined or converted.

## Group behavior

Groups are public, so the rules are stricter and largely separate from private chat:

- **No numbers, ever** — price, duration, schedule and seat counts are stripped at the code level even if the model emits them.
- **No contact requests** — asking for a phone number in front of a whole group is never acceptable; the bot links to its private chat instead.
- **No catalog listings or qualifying questions** — those belong in DM.
- **Silence by default** — reactions, emoji and off-topic chatter get `NO_REPLY` (nothing is sent at all).
- **Real questions** get one short sentence plus a DM link — a registration link if the intent is unambiguous, an info link otherwise.
- **Complaints** are acknowledged briefly, moved to DM, and flagged to the owner.
- A **20-second cooldown** between the bot's own group messages prevents it from flooding the chat.

## Architecture

Each store connects **its own Telegram bot** (recommended) or uses the shared platform bot. Deep links route a user to the right tenant:

```
https://t.me/<bot>?start=admin_<store-uuid>      → claims store ownership (send only to the real owner)
https://t.me/<bot>?start=store_<store-uuid>      → customer, info intent
https://t.me/<bot>?start=register_<store-uuid>   → customer, explicit registration intent (faster path)
```

A `CustomerSession` pins a Telegram user to whichever store's link they last clicked, so the AI always knows which business it represents. Anyone messaging with no valid link or session is politely redirected — never silently attached to a random store.

```
Telegram  →  webhook (HMAC secret verified)  →  Celery task (async, idempotent)
                                                      │
                                                      ├─ content moderation (pre-AI, no tokens spent)
                                                      ├─ rate limits (per customer / global / per store)
                                                      ├─ resolve Store (deep link / session)
                                                      ├─ per-customer lock (one customer's messages
                                                      │  are serialized; different customers run
                                                      │  fully in parallel)
                                                      ├─ Gemini (store-scoped prompt + catalog)
                                                      ├─ deterministic output guards (see above)
                                                      ├─ validate contact → create Lead
                                                      └─ reply + notify owner + CRM sync
```

The webhook only validates, enqueues and returns `200` immediately, so a slow AI call never blocks Telegram's delivery.

## Safety layers

Three independent layers, because the model alone is not trustworthy:

**1. Before the AI** (`check_content_safety`) — the message never reaches Gemini:
- profanity and insults (uz / ru / en)
- prompt injection ("ignore all previous instructions", "system prompt", "jailbreak")
- off-topic categories: religion, politics, sexual content, hacking

> That last group is **catalog-aware**: an Arabic-language center's customers can ask about the Quran, and a cybersecurity school's customers can ask about hacking, without being blocked. Common Uzbek given names (*Islom*, *Imon*) are deliberately excluded from the religion list so a customer giving their name is never rejected.

**2. Limits** — 5 messages/minute per customer; 15/minute and 60/day globally; a per-store monthly cap; messages truncated at 2000 characters.

**3. After the AI** — the output guards listed under [Conversation flow](#conversation-flow), plus:
- `sanitize_telegram_html` — escapes stray `&`/`<` while keeping supported tags, so a course named "Java Backend **&** Spring Boot" can't break Telegram's parser (which used to make customers see literal `<b>` tags)
- `escape_html` on every customer-controlled value interpolated into owner notifications
- `_scrub_leaked_reasoning` — catches the model leaking its own internal reasoning into a customer-facing reply

Additional invariants worth knowing when extending the code:

- **Multi-tenant isolation lives at the auth layer**, not per-view — `get_store_from_request()` is the single source of truth, and every viewset filters through it.
- **The AI's word is never proof of success.** A conversation is marked "registered" only if a `Lead` row was actually written.
- **Secrets at rest are encrypted** (`EncryptedCharField`, Fernet): bot tokens, CRM webhook URLs. Bot tokens additionally store a SHA-256 hash for lookups, since Fernet output differs per encryption.
- **Webhook signatures fail closed** — a missing signing secret in production rejects the request rather than accepting it unverified.

## Tech stack

- **Backend**: Django 6, Django REST Framework, PostgreSQL, Redis
- **Async**: Celery worker + beat (queues: `webhooks`, `messages`, `notifications`, `maintenance`)
- **AI**: Google Gemini (`gemini-3.6-flash`) with model fallback, 25s timeout, bounded retries
- **Auth**: Telegram `initData` HMAC verification (TWA) + JWT for non-Telegram access
- **Integrations**: Bitrix24, Google Sheets (both with background retry), Excel export
- **Docs**: OpenAPI 3 via `drf-spectacular` (Swagger + Redoc)
- **Infra**: fully Dockerized — Postgres, Redis, Django (gunicorn), Celery worker, Celery beat, reverse proxy
- **Monitoring**: Sentry (optional)
- **Frontend**: Next.js (React 19), statically exported and served by this backend

## Project layout

```
apps/
  core/          Shared base models, Telegram initData auth, production config checks
  stores/        Store (tenant) model, onboarding, bot connection, CRM settings
  customers/     Customer + CustomerSession (deep-link → store routing), follow-up tasks
  products/      Catalog (courses / services), full_info script, AI-facing search
  orders/        Lead model, Excel export, CRM retry tasks
  chat/          Gemini integration, prompt, output guards, lead creation, senders
  webhooks/      Telegram & Instagram receivers + Celery processing pipeline
  audit/         Platform error log (CRM failures, AI failures, lead-creation failures)
  integrations/  Bitrix24 / Google Sheets clients
  api/           API v1 URL routing, OpenAPI schema
static/twa/      Built TWA dashboard, served at /app/
static/ops/      Built Super Admin panel, served at /ops/
```

## Getting started

Everything runs in Docker — no local Python or Postgres needed.

```bash
git clone <this-repo>
cd AI-Inbox-backend
cp .env.example .env   # fill in SECRET_KEY, GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, FIELD_ENCRYPTION_KEY, …
docker compose up -d
docker compose exec web python manage.py migrate
```

API: `http://localhost/api/v1/` · docs: `http://localhost/api/v1/docs/` · dashboard: `http://localhost/app/`

### Exposing it to real Telegram

Telegram needs a public HTTPS URL. For local development a quick tunnel works:

```bash
cloudflared tunnel --url http://localhost:80
```

Point `.env`'s `PUBLIC_URL` at the tunnel URL, recreate `web`, then register the webhook:

```bash
docker compose exec web python manage.py setup_bot --url https://<your-tunnel>
```

> ⚠️ A quick tunnel has no uptime guarantee and its URL changes on every restart — you'll be re-registering webhooks constantly. Move to a stable domain before onboarding real customers.

### After recreating the `web` container

The reverse proxy caches the `web` container's resolved IP. If you see `502` after `docker compose up -d web`:

```bash
docker compose restart nginx
```

If containers show as `Up` but nothing responds at all, the Docker network itself has usually broken — recreate it (data in named volumes is preserved):

```bash
docker compose down && docker compose up -d
```

## Onboarding a store

```bash
# 1. Create the store and print both links
docker compose exec web python manage.py create_store --name "PDP Academy" --category education

# 2. Send the 👑 admin link to the business owner (claims ownership)
# 3. Give the 🛍️ customer link to marketing (Instagram bio, ads, group pin, …)
```

The owner opens the admin link once, taps Start, and their Telegram account is bound to that store. They can then connect their **own** bot from the dashboard, which is what customers will actually message.

### Giving a course its full script

The "send the full details after a refusal" behavior only works if the course has its text stored. It is captured automatically when a course is added **via file upload** (the AI extracts the complete text, verbatim for `.txt`/`.md`), and can be pasted or edited by hand in the dashboard's **"To'liq ma'lumot"** field. Courses imported through the bulk onboarding flow do **not** get it — they need it added manually.

## Super Admin panel

A dashboard for the platform operator at `/ops/`, built from a separate Next.js repo (`AI-Inbox-ops-frontend`) so its code never ships to tenant browsers. Create stores, browse businesses, see platform-wide stats.

One-time setup per environment:

```bash
docker compose exec web python manage.py createsuperuser
```

Any Django user with `is_staff=True` can log in; the login screen uses the existing `/api/v1/token/` JWT endpoint and verifies `is_staff` via `/api/v1/superadmin/me/`. Deploy it like the TWA: `./deploy_ops.sh`

## Management commands

| Command | Purpose |
|---|---|
| `create_store --name NAME --category {education,services}` | Onboard a new tenant, print both links |
| `setup_bot --url PUBLIC_URL` | Register the platform bot's webhook, menu and commands |
| `get_admin_link --store NAME_OR_UUID` | Re-print a store's admin/customer links |
| `list_stores [--name NAME]` | List stores with UUID, owner status, counts |
| `revoke_store_owner --store NAME_OR_UUID` | Unbind the current owner |
| `set_store_access --store NAME_OR_UUID --active {true,false}` | Suspend/reactivate a store, data preserved |
| `check_bot_health` / `check_ai_health` | Verify every store's bot webhook and the AI backend |
| `check_debug` | Confirm production settings aren't running in debug mode |
| `encrypt_legacy_secrets` | One-off migration of plaintext secrets to encrypted fields |
| `reset_test_customer --store NAME --username U` | ⚠️ Hard-delete a test customer + their messages/leads |
| `seed_demo_data` / `seed_products` / `seed_load_test` | Seed data for local development |

Commands with a `--store` argument refuse to guess when a name matches more than one store — they list the candidates with UUIDs instead.

## API

- `GET /api/v1/docs/` — Swagger UI
- `GET /api/v1/redoc/` — Redoc
- `GET /api/v1/schema/` — raw OpenAPI 3 schema

Every business-data endpoint (`/orders/`, `/products/`, `/customers/`, `/chat/`, `/store/`) is tenant-scoped: a request resolves to exactly one Store via a verified Telegram `initData` header or a JWT user's own store. There is no way to read or write another tenant's data by passing an ID.

> `/orders/` serves **leads** and is read-only (list + retrieve). Leads can only be created through the conversation pipeline, which is what guarantees contact validation — there is no API path that bypasses it.

## Testing

```bash
docker compose exec web python manage.py test            # everything (~600 tests)
docker compose exec web python manage.py test apps.chat  # one app
```

Most tests target the conversation guards and are written as regression tests for bugs found in live testing — each names the date and the exact conversation that failed. External services (Gemini, Telegram, Bitrix24, Sheets) are mocked; no test requires a live API key.

> If a test run is interrupted, the leftover test database makes the next run hang on a confirmation prompt. Use `--noinput`.

## Production deployment

Use `docker-compose.prod.yml`, which differs from the development file in ways that matter:

- **Postgres and Redis ports are not published** — in development they're exposed on the host for GUI tools; on a public server that would expose both to the internet (Redis has no password by default).
- **`DEBUG=False` is forced** via the `environment` block, which overrides `.env`. This matters because `DEBUG=True` disables webhook signature verification entirely and sets `ALLOWED_HOSTS=["*"]`.
- Containers restart automatically after a reboot.

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

**Generate fresh secrets on the server** — never copy development values:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"  # SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(24))"                                                 # DB_PASSWORD, TELEGRAM_WEBHOOK_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"                    # FIELD_ENCRYPTION_KEY
```

The app **refuses to start** if production is misconfigured (placeholder `SECRET_KEY`, missing `TELEGRAM_WEBHOOK_SECRET` or `FIELD_ENCRYPTION_KEY`, wildcard `ALLOWED_HOSTS`) — see `apps/core/checks.py`. That's deliberate: a silent insecure start is worse than a loud failure.

Once a domain and TLS certificate are in place, set `SECURE_SSL_REDIRECT=True` and `SECURE_HSTS_SECONDS=31536000` in `.env`. Leave them off until then, or HTTP access breaks.

Remaining manual steps: point DNS at the server, obtain a certificate (e.g. certbot), restrict the firewall to ports 22/80/443, and rebuild the TWA against the production domain (`./deploy_twa.sh`).

## CI/CD

**CI (`.github/workflows/ci.yml`)** runs on every push/PR to `main`:
- Django system check + `makemigrations --check` (catches a model change missing its migration)
- Migrations applied end-to-end against a throwaway Postgres
- Docker image build

**CD (`.github/workflows/deploy.yml`)** is a ready template, currently manual-trigger only. To activate: add `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH` secrets and uncomment the `push` trigger. It SSHes in, pulls, rebuilds `web`/`celery_worker`/`celery_beat`, restarts the proxy, and runs migrations.

## Frontend

The TWA dashboard is a separate Next.js repo, statically exported into `static/twa/` and served at `/app/`:

```bash
./deploy_twa.sh     # builds the frontend and copies it in
```

> Editing the frontend source has **no effect** on the live app until this script runs.

The [Super Admin panel](#super-admin-panel) follows the same pattern (`./deploy_ops.sh` → `static/ops/` → `/ops/`).

## Roadmap

- [x] Telegram lead-generation MVP: multi-tenant AI chat, TWA dashboard, lead pipeline
- [x] Deterministic guard layer over the AI's output
- [x] Content moderation with per-tenant catalog awareness
- [x] Production hardening (secret encryption, startup config checks, prod compose)
- [ ] Move off the ephemeral tunnel onto a real server + domain
- [ ] Instagram DM integration (webhook code exists; needs Meta App Review + stable domain)
- [ ] Payment integration (Payme/Click) — subscription fields exist on `Store`, not yet enforced
- [ ] Migrate from the deprecated `google-generativeai` SDK to `google-genai`

---

*Billing is deliberately deferred until the lead-capture experience is validated with real paying businesses — a sequencing choice, not an oversight.*
