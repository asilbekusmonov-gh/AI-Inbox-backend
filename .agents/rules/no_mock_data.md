---
trigger: always_on
description: Mock ma'lumotlar (mock data) mutlaqo ishlatilmaydi, barchasi to'g'ridan-to'g'ri backend API va baza bilan ishlashi shart.
---

# Strictly No Mock Data Rule

- **Do NOT use mock data**: Never introduce hardcoded mock objects, dummy fallback data, or fake API responses for frontend or backend features.
- **Direct Backend Integration**: All features, components, and services MUST fetch, process, and mutate real data directly from the actual backend database and API.
- **Real Error Handling**: If an API or database query fails or returns empty results, present real loading/empty/error states instead of using fake fallback data.
