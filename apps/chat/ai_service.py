"""
AI Xizmati — Gemini API integratsiyasi.

Ishlash mantig'i:
1. Do'konning system_prompt'ini oladi
2. Mijoz bilan bo'lgan suhbat tarixini DB'dan yuklaydi
3. Gemini API'ga jo'natadi
4. Javobni buyurtma JSON uchun tekshiradi
5. Javob matnini qaytaradi

Edge-case qoidalari:
- API xatolarida retry
- Bo'sh yoki noto'g'ri javobda fallback xabar
- Buyurtma JSON'ini matndan ajratib olish
"""
import json
import logging
import re
import time
from typing import Optional
from dataclasses import dataclass

import google.generativeai as genai
from django.conf import settings

logger = logging.getLogger("apps.chat")

# ─────────────────────────────────────────────────────────────
# KONSTANTLAR
# ─────────────────────────────────────────────────────────────

# Suhbat tarixidan nechta xabar yuklanadi (token tejaш uchun)
MAX_HISTORY_MESSAGES = 20

# AI javobida buyurtma topildi degan signal
ORDER_TRIGGER_KEYWORDS = [
    "buyurtma_malumotlari",
    "ORDER_DATA",
    "order_data",
]

# Fallback javob (AI ishlamasa)
FALLBACK_RESPONSE = (
    "Uzr, hozir texnik muammo yuz berdi. "
    "Iltimos, bir oz kutib, qayta yozing. 🙏"
)


# ─────────────────────────────────────────────────────────────
# DATA CLASSLAR
# ─────────────────────────────────────────────────────────────

@dataclass
class AIResponse:
    """AI'dan kelgan javobning tuzilgan ko'rinishi"""
    text: str                          # Mijozga ko'rsatiladigan matn
    tokens_used: int                   # Sarflangan tokenlar
    model_used: str                    # Qaysi model javob berdi
    order_data: Optional[dict] = None  # Buyurtma ma'lumotlari (topilsa)
    has_order: bool = False            # Buyurtma aniqlangani


# ─────────────────────────────────────────────────────────────
# SYSTEM PROMPT BUILDER
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """
{store_prompt}

---
## Do'konda Mavjud Tegishli Mahsulotlar (Katalog Ma'lumotlari):
{products_context}

---
## Muhim Ko'rsatmalar (Doim rioya qil):

1. **Narx va Zaxira (Stock)**: Mahsulot narxi, xususiyatlari va ombordagi mavjudligi haqida FAQAT yuqoridagi katalog ma'lumotlariga tayan. Narxlarni yoki mavjud emas mahsulotlarni O'YLAB TOPMA.
   - Garroq ma'lumot bo'lmasa: "Narx yoki mavjudlikni operatorimiz aniqlashtirib beradi" de.
   - Stock 0 bo'lsa: "Hozircha omborda tugagan" deb tushuntir.

2. **Til**: Foydalanuvchi qaysi tilda yozsa, shu tilda javob ber.
   (O'zbek, Rus yoki boshqa til)

3. **Buyurtma olish**: Mijoz mahsulot sotib olmoqchi bo'lsa:
   - Avval qaysi mahsulot va nechtasini so'ra
   - Keyin to'liq ismini so'ra
   - Telefon raqamini so'ra (+998 formatida)
   - Yetkazib berish manzilini so'ra
   - Hammasini olgandan so'ng tasdiqlat

4. **Buyurtmani yopish**: Barcha ma'lumotlar (ism, raqam, manzil) to'liq
   bo'lganda, javob oxiriga AYNAN quyidagi formatda JSON qo'sh:

```json
buyurtma_malumotlari:
{{
  "full_name": "Mijoz to'liq ismi",
  "phone": "+998901234567",
  "address": "To'liq manzil",
  "items": [
    {{"name": "Mahsulot nomi", "qty": 1, "price": 0}}
  ],
  "notes": "Qo'shimcha izoh (ixtiyoriy)"
}}
```

5. **Qoidalar**:
   - Hech qachon boshqa do'konlar haqida gapirma
   - Doim muloyim va professional bo'l
   - Javobni qisqa va aniq yoz
""".strip()


def build_system_prompt(store, user_message: str = "") -> str:
    """Do'kon system prompt'ini va mahsulotlar kontekstini tuzadi"""
    from apps.products.models import Product

    try:
        matched_products = Product.search_for_ai(store, user_message, limit=5)
        if matched_products.exists():
            products_list = []
            for p in matched_products:
                desc = f" ({p.description})" if p.description else ""
                sku = f" [SKU: {p.sku}]" if p.sku else ""
                products_list.append(
                    f"• {p.name}{sku}{desc} — Narxi: {p.price:,.0f} so'm | Ombor: {p.stock} dona"
                )
            products_context = "\n".join(products_list)
        else:
            products_context = "Hozircha katalogda mos mahsulotlar ko'rsatilmadi yoki aktiv mahsulotlar yo'q."
    except Exception as e:
        logger.error(f"Mahsulotlar kontekstini olishda xato: {e}")
        products_context = "Mahsulotlar haqida ma'lumot yuklanmadi."

    return SYSTEM_PROMPT_TEMPLATE.format(
        store_prompt=store.ai_system_prompt or "Siz onlayn do'kon yordamchisisiz.",
        products_context=products_context,
    )


# ─────────────────────────────────────────────────────────────
# GEMINI CLIENT
# ─────────────────────────────────────────────────────────────

def _get_gemini_client():
    """Gemini API client'ini qaytaradi"""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY sozlanmagan!")
    genai.configure(api_key=api_key)
    return genai


def _load_conversation_history(store, customer) -> list[dict]:
    """
    DB'dan so'nggi N ta xabarni yuklaydi va
    Gemini formatiga o'giradi.

    Returns:
        [{"role": "user", "parts": ["matn"]}, ...]
    """
    from apps.chat.models import ChatMessage

    try:
        messages = (
            ChatMessage.objects.filter(
                store=store,
                customer=customer,
                is_deleted=False,
                processing_status=ChatMessage.ProcessingStatus.COMPLETED,
                role__in=[
                    ChatMessage.Role.USER,
                    ChatMessage.Role.ASSISTANT,
                ],
            )
            .order_by("-created_at")[:MAX_HISTORY_MESSAGES]
        )

        # Gemini API uchun tarix qoidasi: user -> model -> user -> model almashishi shart
        history = []
        last_role = None

        for msg in reversed(list(messages)):
            role = "user" if msg.role == ChatMessage.Role.USER else "model"

            # Tarix doim 'user' bilan boshlanishi kerak
            if not history and role != "user":
                continue

            # Ketma-ket bir xil role kelmasligi kerak
            if role != last_role and msg.content:
                history.append({
                    "role": role,
                    "parts": [{"text": msg.content}],
                })
                last_role = role

        # Oxirgi element 'model' bo'lsa yaxshi (keyingi xabar 'user' bo'ladi)
        return history

    except Exception as e:
        logger.error(f"Suhbat tarixini yuklashda xato: {e}", exc_info=True)
        return []


# ─────────────────────────────────────────────────────────────
# ASOSIY AI FUNKSIYA
# ─────────────────────────────────────────────────────────────

def get_ai_response(store, customer, user_message: str) -> AIResponse:
    """
    Gemini API'dan javob oladi. 429 Rate Limit bo'lsa zaxira modellar bilan qayta urinadi.
    """
    fallback_models = [
        "gemini-3.6-flash",
        "gemini-flash-latest",
    ]
    last_error = None

    for model_name in fallback_models:
        try:
            return _call_gemini(store, customer, user_message, model_name=model_name)
        except Exception as e:
            last_error = e
            logger.warning(f"Gemini API xatosi ({model_name}): {e}")
            time.sleep(1)

    logger.error(f"Gemini API barcha modellarda javob bermadi: {last_error}", exc_info=True)
    return AIResponse(
        text=FALLBACK_RESPONSE,
        tokens_used=0,
        model_used=store.ai_model,
    )


def _call_gemini(store, customer, user_message: str, model_name: str = "gemini-2.5-flash") -> AIResponse:
    """
    Gemini API'ga so'rov yuboradi.
    """
    client = _get_gemini_client()

    # System prompt (Product context bilan birga)
    system_prompt = build_system_prompt(store, user_message)

    # Suhbat tarixi
    history = _load_conversation_history(store, customer)

    # Model yaratish
    model = client.GenerativeModel(
        model_name=model_name,
        system_instruction=system_prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=store.ai_temperature,
            max_output_tokens=store.ai_max_tokens,
            candidate_count=1,
        ),
    )

    # Suhbat boshlash (tarix bilan, agar xato bo'lsa tarixsiz)
    try:
        chat = model.start_chat(history=history)
        response = chat.send_message(user_message)
    except Exception as e:
        logger.warning(f"Suhbat tarixida xato, tarixsiz qayta urilinmoqda: {e}")
        chat = model.start_chat(history=[])
        response = chat.send_message(user_message)

    # Javob matni
    response_text = response.text or ""

    # Token hisoblash
    tokens_used = 0
    try:
        tokens_used = response.usage_metadata.total_token_count or 0
    except AttributeError:
        pass

    # Buyurtma ma'lumotlarini tekshirish
    order_data = _extract_order_data(response_text)

    # Har doim mijozga yuboriladigan matnni tozalaymiz (JSON bloklarisiz)
    clean_text = _clean_response_text(response_text)

    logger.info(
        f"Gemini javob olindi | model={model_name} | "
        f"tokens={tokens_used} | has_order={order_data is not None}"
    )

    return AIResponse(
        text=clean_text,
        tokens_used=tokens_used,
        model_used=model_name,
        order_data=order_data,
        has_order=order_data is not None,
    )


# ─────────────────────────────────────────────────────────────
# BUYURTMA ANIQLASH (ORDER EXTRACTION)
# ─────────────────────────────────────────────────────────────

def _extract_order_data(response_text: str) -> Optional[dict]:
    """
    AI javobidan buyurtma JSON'ini ajratib oladi.

    Qidirilayotgan format:
    ```
    buyurtma_malumotlari:
    { ... JSON ... }
    ```

    Returns:
        dict — buyurtma ma'lumotlari (topilsa)
        None — buyurtma topilmadi
    """
    if not response_text:
        return None

    # Trigger kalit so'z bor-yo'qligini tekshiramiz
    has_trigger = any(
        keyword in response_text
        for keyword in ORDER_TRIGGER_KEYWORDS
    )
    if not has_trigger:
        return None

    try:
        # JSON bloklarini qidiramiz (```json ... ``` yoki oddiy { ... })
        patterns = [
            r"```json\s*\n?(.*?)\n?```",      # ```json ... ```
            r"```\s*\n?(\{.*?\})\s*\n?```",   # ``` { ... } ```
            r"buyurtma_malumotlari:\s*(\{.*?\})",  # to'g'ridan-to'g'ri
            r"ORDER_DATA:\s*(\{.*?\})",
        ]

        for pattern in patterns:
            match = re.search(pattern, response_text, re.DOTALL | re.IGNORECASE)
            if match:
                json_str = match.group(1).strip()
                data = json.loads(json_str)

                # Minimal validatsiya
                required_fields = ["full_name", "phone", "address"]
                if all(data.get(field) for field in required_fields):
                    logger.info(f"Buyurtma aniqlandi: {data.get('full_name')}")
                    return data
                else:
                    logger.warning(
                        f"Buyurtma JSON topildi lekin to'liq emas: {data}"
                    )

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Buyurtma JSON parse xatosi: {e}")

    return None


def _clean_response_text(text: str) -> str:
    """
    AI javobidan JSON blokini o'chiradi. Mijoz faqat xushmuomala matnni ko'radi.
    """
    if not text:
        return ""

    # ```json buyurtma_malumotlari: ... ``` va oddiy JSON bloklarini o'chirish
    text = re.sub(r"```(?:json)?\s*(?:buyurtma_malumotlari:?)?.*?```", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"buyurtma_malumotlari:\s*\{.*?\}", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()
