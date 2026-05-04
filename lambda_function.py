import os
import logging
from dotenv import load_dotenv

load_dotenv()  # no-op in Lambda; used for local dev

import dynamo_client
import gmail_client
import email_parser
import splitwise_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_STORES = ["Costco", "Food Lion"]

# Parsed from env: "4035:36896689,0636:48292153,4141:61548829"
CARD_TO_USER = {
    card: int(uid)
    for part in os.environ["CARD_TO_USER"].split(",")
    for card, uid in [part.strip().split(":")]
}


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

        try:
            expense_id = splitwise_client.create_grocery_expense(total, store, order_date, payer_id, instacart_order_id)
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
