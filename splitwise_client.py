import os
import logging
from splitwise import Splitwise
from splitwise.expense import Expense
from splitwise.user import ExpenseUser

logger = logging.getLogger(__name__)

SPLITWISE_CONSUMER_KEY = os.environ["SPLITWISE_CONSUMER_KEY"]
SPLITWISE_CONSUMER_SECRET = os.environ["SPLITWISE_CONSUMER_SECRET"]
SPLITWISE_BEARER_TOKEN = os.environ["SPLITWISE_BEARER_TOKEN"]
SPLITWISE_GROUP_ID = int(os.environ["SPLITWISE_GROUP_ID"])
SPLITWISE_USER_IDS = [int(uid) for uid in os.environ["SPLITWISE_USER_IDS"].split(",")]


def _build_client() -> Splitwise:
    return Splitwise(
        SPLITWISE_CONSUMER_KEY,
        SPLITWISE_CONSUMER_SECRET,
        api_key=SPLITWISE_BEARER_TOKEN,
    )


def create_grocery_expense(
    total: float,
    store: str,
    order_date: str,
    payer_id: int,
    instacart_order_id: str = None,
    notes: str = None,
    owed_shares: dict = None,
) -> str:
    """Create expense. owed_shares: {user_id: amount}. Falls back to equal split if None."""
    client = _build_client()

    if owed_shares:
        active_ids = list(owed_shares.keys())
    else:
        active_ids = SPLITWISE_USER_IDS
        n = len(active_ids)
        share = round(total / n, 2)
        remainder = round(total - share * n, 2)
        owed_shares = {
            uid: share + (remainder if i == 0 else 0.0)
            for i, uid in enumerate(active_ids)
        }

    expense = Expense()
    expense.cost = str(total)
    expense.currency_code = "USD"
    order_suffix = f" #{instacart_order_id}" if instacart_order_id else ""
    expense.description = f"Groceries – {store} ({order_date}){order_suffix}"
    if notes:
        expense.details = notes
    expense.group_id = SPLITWISE_GROUP_ID
    expense.split_equally = False

    users = []
    for uid, owed in owed_shares.items():
        u = ExpenseUser()
        u.id = uid
        u.paid_share = str(round(total if uid == payer_id else 0.0, 2))
        u.owed_share = str(round(owed, 2))
        users.append(u)

    expense.users = users
    created, errors = client.createExpense(expense)

    if errors:
        raise RuntimeError(f"Splitwise error: {errors.errors}")

    logger.info("Created Splitwise expense %s for $%.2f at %s", created.id, total, store)
    return str(created.id)
