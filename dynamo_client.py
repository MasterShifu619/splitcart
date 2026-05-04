import os
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "processed_orders")
_dynamo = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_table = _dynamo.Table(TABLE_NAME)


def is_duplicate(email_id: str) -> bool:
    response = _table.get_item(Key={"email_id": email_id})
    return "Item" in response


def record_order(
    email_id: str,
    order_total: float,
    store_name: str,
    splitwise_expense_id: str,
    instacart_order_id: str = None,
    status: str = "success",
) -> None:
    item = {
        "email_id": email_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "order_total": str(order_total),
        "store_name": store_name,
        "splitwise_expense_id": splitwise_expense_id,
        "status": status,
    }
    if instacart_order_id:
        item["instacart_order_id"] = instacart_order_id
    _table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(email_id)",  # safe concurrent guard
    )
    logger.info("Recorded order %s → Splitwise %s", email_id, splitwise_expense_id)


def record_failure(email_id: str, order_total: float, store_name: str, error: str) -> None:
    _table.put_item(
        Item={
            "email_id": email_id,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "order_total": str(order_total),
            "store_name": store_name,
            "splitwise_expense_id": "",
            "status": "failed",
            "error": error,
        }
    )
