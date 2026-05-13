from dotenv import load_dotenv; load_dotenv()
import os
import json
import re
import voyageai
from pinecone import Pinecone

DUMP_FILE = os.path.join(os.path.dirname(__file__), "dump_expenses_output.txt")

USER_NAMES = {
    36896689: "Bipin",
    61548829: "Mahim",
    48292153: "Varun",
    68880174: "Deepanshu",
}

GROCERY_KEYWORDS = ["food lion", "costco", "groceries", "grocery", "six twelve", "chapati"]
NOISE_KEYWORDS = ["payment", "rent", "uber", "internet", "cab"]

_ITEM_PRICE_RE = re.compile(r"^(.+?):\s*\$[\d.]+$")
_PAREN_ITEMS_RE = re.compile(r"\(([^)]+)\)")
_TOTAL_LABELS = {"Items Subtotal", "Sales Tax", "Service Fee", "Total"}

voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index(os.environ["PINECONE_INDEX"])


def is_grocery(expense: dict) -> bool:
    desc = expense["description"].lower()
    if any(kw in desc for kw in NOISE_KEYWORDS):
        return False
    return any(kw in desc for kw in GROCERY_KEYWORDS)


def extract_items(expense: dict) -> list[str]:
    items = []

    details = expense.get("details") or ""
    if details:
        for line in details.splitlines():
            m = _ITEM_PRICE_RE.match(line.strip())
            if m:
                name = m.group(1).strip()
                if name not in _TOTAL_LABELS and name.isascii():
                    items.append(name)

    if not items:
        desc = expense["description"]
        m = _PAREN_ITEMS_RE.search(desc)
        if m:
            items = [i.strip() for i in m.group(1).split(",") if i.strip()]

    return items


def classify_split(expense: dict) -> tuple[str, list[int]]:
    users = expense.get("users", [])
    active = [u for u in users if float(u["owed"]) > 0]
    active_ids = [u["id"] for u in active]
    split_type = "shared" if len(active_ids) >= 3 else "personal"
    return split_type, active_ids



def expense_to_chunks(expense: dict) -> list[dict]:
    items = extract_items(expense)
    if not items:
        return []

    split_type, active_ids = classify_split(expense)
    names = [USER_NAMES.get(uid, str(uid)) for uid in active_ids]
    date = expense["date"][:10]
    exp_id = expense["id"]
    chunks = []

    for item in items:
        if split_type == "personal":
            payer = next(
                (u for u in expense["users"] if float(u["paid"]) > 0), None
            )
            payer_name = USER_NAMES.get(payer["id"], "unknown") if payer else "unknown"
            if len(active_ids) == 1:
                text = (
                    f"'{item}' was bought on {date} as a personal item "
                    f"by {names[0]} only. Paid by {payer_name}."
                )
            else:
                text = (
                    f"'{item}' was bought on {date} and split personally "
                    f"between {' and '.join(names)} only (not shared with all roommates). "
                    f"Paid by {payer_name}."
                )
        else:
            text = (
                f"'{item}' was bought on {date} and split as a shared expense "
                f"among {', '.join(names)}."
            )

        safe_item = re.sub(r"[^a-zA-Z0-9_-]", "_", item[:30])
        chunks.append({
            "id": f"{exp_id}_{safe_item}",
            "text": text,
            "metadata": {
                "text": text,
                "item": item,
                "split_type": split_type,
                "users": [str(uid) for uid in active_ids],
                "date": date,
            },
        })

    return chunks


def main():
    with open(DUMP_FILE) as f:
        content = f.read()

    raw_expenses = [
        block.strip()
        for block in content.split("---")
        if block.strip()
    ]

    all_chunks = []
    skipped = 0
    for raw in raw_expenses:
        try:
            expense = json.loads(raw)
        except json.JSONDecodeError:
            skipped += 1
            continue

        if not is_grocery(expense):
            continue

        chunks = expense_to_chunks(expense)
        all_chunks.extend(chunks)

    print(f"Total chunks from history: {len(all_chunks)} (skipped {skipped} malformed blocks)")

    batch_size = 50
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        texts = [c["text"] for c in batch]
        result = voyage.embed(texts, model="voyage-3", input_type="document")
        vectors = [
            {
                "id": c["id"],
                "values": emb,
                "metadata": c["metadata"],
            }
            for c, emb in zip(batch, result.embeddings)
        ]
        index.upsert(vectors=vectors, namespace="history")
        print(f"  Upserted batch {i // batch_size + 1} ({len(vectors)} vectors)")

    print(f"\nDone. {len(all_chunks)} history chunks in Pinecone namespace 'history'")


if __name__ == "__main__":
    main()
