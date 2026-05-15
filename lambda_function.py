import os
import logging
from dotenv import load_dotenv

load_dotenv()  # no-op in Lambda; used for local dev

import dynamo_client
import gmail_client
import email_parser
import splitwise_client
import item_splitter

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

ALLOWED_STORES = ["Costco", "Food Lion"]

# Parsed from env: "4035:36896689,0636:48292153,4141:61548829"
CARD_TO_USER = {
    card: int(uid)
    for part in os.environ["CARD_TO_USER"].split(",")
    for card, uid in [part.strip().split(":")]
}


USER_NAMES = {
    36896689: "Bipin",
    61548829: "Mahim",
    48292153: "Varun",
    68880174: "Deepanshu",
}


def _build_smart_notes(items, assignments, tax, service_fee, owed_shares):
    assign_map = {a["item"]: a["assign_to"] for a in assignments}
    lines = []

    for item in items:
        name = item["name"]
        price = item["price"]
        assign_to = assign_map.get(name, "shared")
        if assign_to == "shared":
            tag = "Shared"
        else:
            tag = f"{USER_NAMES.get(assign_to, str(assign_to))} (personal)"
        lines.append(f"{name}: ${price:.2f} → {tag}")

    lines.append("")
    lines.append(f"Sales Tax: ${tax:.2f}")
    lines.append(f"Service Fee: ${service_fee:.2f}")
    lines.append("")
    lines.append("Split:")
    for uid, amount in owed_shares.items():
        lines.append(f"  {USER_NAMES.get(uid, str(uid))}: ${amount:.2f}")

    return "\n".join(lines)


def _compute_owed_shares(items, assignments, tax, service_fee, active_user_ids):
    n = len(active_user_ids)
    owed = {uid: 0.0 for uid in active_user_ids}
    shared_subtotal = 0.0

    assign_map = {a["item"]: a["assign_to"] for a in assignments}

    for item in items:
        price = item["price"]
        assign_to = assign_map.get(item["name"], "shared")
        if assign_to != "shared" and assign_to in owed:
            owed[assign_to] += price
        else:
            shared_subtotal += price

    shared_total = shared_subtotal + tax + service_fee
    share = round(shared_total / n, 2)
    remainder = round(shared_total - share * n, 2)

    for i, uid in enumerate(active_user_ids):
        owed[uid] += share + (remainder if i == 0 else 0.0)
        owed[uid] = round(owed[uid], 2)

    return owed


def lambda_handler(event, context):
    processed = 0
    skipped = 0
    failed = 0

    for message in gmail_client.fetch_unread_instacart_emails():
        email_id = message["id"]

        if dynamo_client.is_duplicate(email_id):
            logger.info("Skipping duplicate email %s", email_id)
            skipped += 1
            continue

        parsed = email_parser.parse_instacart_email(message)
        if not parsed:
            logger.error("Parse failed for email %s — skipping", email_id)
            failed += 1
            continue

        store = parsed["store"]

        if not any(allowed in store for allowed in ALLOWED_STORES):
            logger.info("Skipping email %s — store '%s' not in allowed list", email_id, store)
            skipped += 1
            continue

        card_last4 = parsed["card_last4"]
        payer_id = CARD_TO_USER.get(card_last4) if card_last4 else None
        if not payer_id:
            logger.info("Skipping email %s — card '%s' not in known mapping", email_id, card_last4)
            skipped += 1
            continue

        order_date = parsed["order_date"]
        total = parsed["total"]
        instacart_order_id = parsed.get("instacart_order_id")
        active_user_ids = splitwise_client.SPLITWISE_USER_IDS

        try:
            owed_shares = None
            notes = parsed.get("notes")
            structured = parsed.get("structured_items")
            if structured and structured["items"]:
                item_names = [it["name"] for it in structured["items"]]
                assignments = item_splitter.classify_items(item_names, active_user_ids)
                owed_shares = _compute_owed_shares(
                    structured["items"], assignments,
                    structured["tax"], structured["service_fee"],
                    active_user_ids,
                )
                notes = _build_smart_notes(
                    structured["items"], assignments,
                    structured["tax"], structured["service_fee"],
                    owed_shares,
                )

            expense_id = splitwise_client.create_grocery_expense(
                total, store, order_date, payer_id, instacart_order_id,
                notes=notes, owed_shares=owed_shares,
            )
            dynamo_client.record_order(email_id, total, store, expense_id, instacart_order_id)
            logger.info("Processed email %s: $%.2f at %s → expense %s", email_id, total, store, expense_id)
            processed += 1
        except Exception as exc:
            logger.error("Failed to create Splitwise expense for %s: %s", email_id, exc)
            dynamo_client.record_failure(email_id, total, store, str(exc))
            failed += 1

    summary = {"processed": processed, "skipped": skipped, "failed": failed}
    logger.info("Done: %s", summary)
    return summary
