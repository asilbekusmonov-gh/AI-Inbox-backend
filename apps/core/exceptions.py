"""
DRF uchun maxsus exception handler.

Barcha xatolarni bir xil formatga keltiradi:
{
    "success": false,
    "error": {
        "code": "not_found",
        "message": "Topilmadi",
        "details": {...}
    }
}
"""
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger("apps.core")


def custom_exception_handler(exc, context):
    """
    DRF standart exception handlerini kengaytiradi.
    Barcha xatolar bir xil JSON formatda qaytadi.
    """
    # Avval DRF standart handlerini chaqiramiz
    response = exception_handler(exc, context)

    if response is not None:
        # DRF tomonidan handle qilingan xato
        error_data = {
            "success": False,
            "error": {
                "code": _get_error_code(response.status_code),
                "message": _extract_message(response.data),
                "details": response.data,
            }
        }
        response.data = error_data
        logger.warning(
            f"API xatosi: {response.status_code} | "
            f"View: {context.get('view')} | "
            f"Xato: {exc}"
        )
    else:
        # DRF handle qilmagan kutilmagan xato (500)
        logger.error(f"Kutilmagan xato: {exc}", exc_info=True)
        response = Response(
            {
                "success": False,
                "error": {
                    "code": "server_error",
                    "message": "Serverda xato yuz berdi. Iltimos, qayta urinib ko'ring.",
                    "details": None,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response


def _get_error_code(status_code: int) -> str:
    """HTTP status code'dan matnli kod hosil qiladi"""
    codes = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        429: "too_many_requests",
        500: "server_error",
    }
    return codes.get(status_code, f"error_{status_code}")


def _extract_message(data) -> str:
    """Response data'dan birinchi xato xabarini oladi"""
    if isinstance(data, dict):
        # "detail" field eng keng tarqalgan
        if "detail" in data:
            return str(data["detail"])
        # Birinchi key'ning qiymatini oladi
        first_value = next(iter(data.values()), None)
        if isinstance(first_value, list) and first_value:
            return str(first_value[0])
        if first_value:
            return str(first_value)
    elif isinstance(data, list) and data:
        return str(data[0])
    return "Xato yuz berdi"
