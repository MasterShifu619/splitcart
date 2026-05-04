import re
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_STORE_RE = re.compile(r"Your order from (.+?) was")
_DATE_RE = re.compile(r"placed on (.+?) and")
_TOTAL_RE = re.compile(r"Total\s+\$([0-9]+\.[0-9]{2})")
_CARD_RE = re.compile(r"\w[\w ]+? ending in (\d{4})")
_ORDER_ID_RE = re.compile(r"Instacart Order Id:\s*\*?\s*(\d+)")


def _decode_body(payload: dict) -> str:
    """Recursively extract plain-text body from Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _decode_body(part)
        if result:
            return result
    return ""


def parse_instacart_email(message: dict) -> Optional[dict]:
    """
    Parse Gmail message dict (from messages.get with format=full).
    Returns {"store", "order_date", "total", "card_last4"} or None if parsing fails.
    card_last4 is None if no card found.
    """
    payload = message.get("payload", {})
    body = _decode_body(payload)

    if not body:
        logger.warning("Empty body for message %s", message.get("id"))
        return None

    store_match = _STORE_RE.search(body)
    date_match = _DATE_RE.search(body)
    total_match = _TOTAL_RE.search(body)
    card_match = _CARD_RE.search(body)
    order_id_match = _ORDER_ID_RE.search(body)

    if not (store_match and date_match and total_match):
        logger.warning(
            "Regex failed for message %s — store=%s date=%s total=%s",
            message.get("id"),
            bool(store_match),
            bool(date_match),
            bool(total_match),
        )
        return None

    return {
        "store": store_match.group(1).strip(),
        "order_date": date_match.group(1).strip(),
        "total": float(total_match.group(1)),
        "card_last4": card_match.group(1) if card_match else None,
        "instacart_order_id": order_id_match.group(1) if order_id_match else None,
    }
