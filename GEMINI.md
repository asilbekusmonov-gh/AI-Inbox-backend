# AI-Inbox Project Guidelines (Full-Stack)

## Core Principles & Rules
1. **STRICTLY NO MOCK DATA**: Hech qanday mock yoki soxta data ishlatilmaydi. Barcha ma'lumotlar real PostgreSQL ma'lumotlar bazasi, Django ORM va real HTTP API lar bilan ishlashi shart.
2. **Direct Integration**: Frontend/TWA (`/home/asilbek/PycharmProjects/Ai-Inbox-frontend`) va Backend (`/home/asilbek/PycharmProjects/AI-Inbox-backend`) o'rtasida faqat real REST API va JSON ma'lumotlar saqlanishi kerak.
3. **Multi-tenant Architecture**: Barcha modellar (`Customer`, `ChatMessage`, `Product`, `Order`) `Store` modeliga Foreign Key orqali bog'langan. Barcha so'rovlar tenant (Store) darajasida izolyatsiya qilinishi shart.
4. **Idempotency**: Webhook orqali keladigan har bir xabar (`message_id` + `store` + `platform`) unikal bo'lishi va qayta ishlanishida dublikatlar paydo bo me'yori saqlanishi shart.

## Repositories & Map
- **Backend**: `/home/asilbek/PycharmProjects/AI-Inbox-backend`
- **Frontend (TWA Next.js)**: `/home/asilbek/PycharmProjects/Ai-Inbox-frontend`
- **Master Prompt File**: [MASTER_PROMPT.md](file:///home/asilbek/PycharmProjects/AI-Inbox-backend/MASTER_PROMPT.md)

> Dynamic rule details and architecture blueprint: `.agents/rules/project_context.md`
