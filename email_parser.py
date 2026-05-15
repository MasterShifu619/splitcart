import re
import base64
import logging
from html.parser import HTMLParser
from typing import Optional

logger = logging.getLogger(__name__)

_STORE_RE = re.compile(r"Your order from (.+?) was")
_DATE_RE = re.compile(r"placed on (.+?) and")
_TOTAL_RE = re.compile(r"Total\s+\$([0-9]+\.[0-9]{2})")
_CARD_RE = re.compile(r"\w[\w ]+? ending in (\d{4})")
_ORDER_ID_RE = re.compile(r"Instacart Order Id:\s*\*?\s*(\d+)")
_QTY_RE = re.compile(r"^\d+(?:\.\d+)? lb x \$[\d.]+$|^\d+ x \$[\d.]+$")
_PRICE_RE = re.compile(r"^\$[\d.]+$")
_TOTALS_LABELS = ("Items Subtotal", "Sales Tax", "Service Fee", "Total")


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def get_text(self):
        return "\n".join(self._parts)


def _extract_mime(payload: dict, mime_target: str) -> str:
    mime = payload.get("mimeType", "")
    if mime == mime_target:
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    result = ""
    for part in payload.get("parts", []):
        result += _extract_mime(part, mime_target)
    return result


def _decode_body(payload: dict) -> str:
    """Return plain text if it has key fields; otherwise strip and use HTML."""
    plain = _extract_mime(payload, "text/plain")
    if plain and _DATE_RE.search(plain) and _TOTAL_RE.search(plain):
        return plain
    html_raw = _extract_mime(payload, "text/html")
    if html_raw:
        stripper = _HTMLStripper()
        stripper.feed(html_raw)
        return stripper.get_text()
    return plain


def _parse_structured_items(body: str) -> Optional[dict]:
    """Returns {"items": [{"name", "price"}], "tax", "service_fee", "subtotal"} or None."""
    lines = body.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "items found"), None)
    end = next((i for i, l in enumerate(lines) if l.strip() == "Order Totals"), None)
    if start is None or end is None:
        return None

    item_lines = lines[start:end]
    items = []
    for i, line in enumerate(item_lines):
        if _QTY_RE.match(line.strip()):
            j = i - 1
            while j >= 0 and item_lines[j].strip().startswith("("):
                j -= 1
            if j < 0:
                continue
            name = item_lines[j].strip()
            for k in range(i + 1, min(i + 8, len(item_lines))):
                if item_lines[k].strip() == "Final item price:" and k + 1 < len(item_lines):
                    price_str = item_lines[k + 1].strip().lstrip("$")
                    try:
                        items.append({"name": name, "price": float(price_str)})
                    except ValueError:
                        pass
                    break

    totals_map = {}
    for i in range(end, len(lines)):
        stripped = lines[i].strip()
        if stripped in _TOTALS_LABELS and i + 1 < len(lines):
            nxt = lines[i + 1].strip().lstrip("$")
            try:
                totals_map[stripped] = float(nxt)
            except ValueError:
                pass

    stated_subtotal = totals_map.get("Items Subtotal", 0.0)
    parsed_sum = round(sum(it["price"] for it in items), 2)
    gap = round(stated_subtotal - parsed_sum, 2)
    if gap > 0.01:
        items.append({"name": "Order adjustments", "price": gap})

    return {
        "items": items,
        "subtotal": stated_subtotal,
        "tax": totals_map.get("Sales Tax", 0.0),
        "service_fee": totals_map.get("Service Fee", 0.0),
    }


def _parse_item_notes(body: str) -> Optional[str]:
    lines = body.splitlines()

    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "items found"), None)
    end = next((i for i, l in enumerate(lines) if l.strip() == "Order Totals"), None)
    if start is None or end is None:
        return None

    item_lines = lines[start:end]
    items = []
    for i, line in enumerate(item_lines):
        if _QTY_RE.match(line.strip()):
            j = i - 1
            while j >= 0 and item_lines[j].strip().startswith("("):
                j -= 1
            if j < 0:
                continue
            name = item_lines[j].strip()
            for k in range(i + 1, min(i + 8, len(item_lines))):
                if item_lines[k].strip() == "Final item price:" and k + 1 < len(item_lines):
                    price = item_lines[k + 1].strip()
                    items.append((name, price))
                    break

    totals = []
    for i in range(end, len(lines)):
        stripped = lines[i].strip()
        if stripped in _TOTALS_LABELS and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if _PRICE_RE.match(nxt):
                totals.append((stripped, nxt))

    if not items and not totals:
        return None

    parts = [f"{name}: {price}" for name, price in items]
    if totals:
        parts.append("")
        parts.extend(f"{label}: {value}" for label, value in totals)
    return "\n".join(parts)


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
        "notes": _parse_item_notes(body),
        "structured_items": _parse_structured_items(body),
    }
