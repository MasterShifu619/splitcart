from dotenv import load_dotenv; load_dotenv()
import json
from splitwise import Splitwise
import os

client = Splitwise(
    os.environ["SPLITWISE_CONSUMER_KEY"],
    os.environ["SPLITWISE_CONSUMER_SECRET"],
    api_key=os.environ["SPLITWISE_BEARER_TOKEN"],
)

group_id = int(os.environ["SPLITWISE_GROUP_ID"])
expenses = client.getExpenses(group_id=group_id, limit=200)

for e in expenses:
    print(json.dumps({
        "id": e.getId(),
        "description": e.getDescription(),
        "cost": e.getCost(),
        "date": str(e.getDate()),
        "details": e.getDetails(),
        "users": [
            {
                "id": u.getId(),
                "paid": u.getPaidShare(),
                "owed": u.getOwedShare(),
            }
            for u in (e.getUsers() or [])
        ],
    }, indent=2))
    print("---")
