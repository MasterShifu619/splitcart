import os
import json
import logging
import voyageai
import boto3
from pinecone import Pinecone

logger = logging.getLogger(__name__)

USER_NAMES = {
    36896689: "Bipin",
    61548829: "Mahim",
    48292153: "Varun",
    68880174: "Deepanshu",
}

voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"))

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "profiles")


def _load_profiles() -> list[dict]:
    profiles = []
    for fname in os.listdir(PROFILES_DIR):
        if fname.endswith(".json"):
            with open(os.path.join(PROFILES_DIR, fname)) as f:
                profiles.append(json.load(f))
    return profiles


def _profile_match(item: str, profiles: list[dict], active_user_ids: list[int]) -> int | None:
    """Returns user_id if item matches a personal item in any active profile, else None."""
    item_lower = item.lower()
    for profile in profiles:
        if profile["splitwise_id"] not in active_user_ids:
            continue
        for personal in profile.get("personal_items", []):
            if personal.lower() in item_lower or item_lower in personal.lower():
                return profile["splitwise_id"]
    return None


def _get_index():
    return pc.Index(os.environ["PINECONE_INDEX"])


def _retrieve(query: str, namespace: str, top_k: int = 5) -> list[str]:
    index = _get_index()
    result = voyage.embed([query], model="voyage-3", input_type="query")
    vector = result.embeddings[0]
    response = index.query(
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )
    return [match["metadata"]["text"] for match in response["matches"]]


def _build_prompt(items: list[str], active_user_ids: list[int], profile_chunks: list[str], history_chunks: list[str]) -> str:
    active_users = {uid: USER_NAMES.get(uid, str(uid)) for uid in active_user_ids}
    users_str = ", ".join(f"{name} (id: {uid})" for uid, name in active_users.items())

    profile_context = "\n".join(f"- {c}" for c in profile_chunks)
    history_context = "\n".join(f"- {c}" for c in history_chunks)
    items_str = "\n".join(f"- {item}" for item in items)

    return f"""You are splitting a grocery bill among roommates. Decide whether each item is shared equally or personal to one person.

Active roommates in this order:
{users_str}

Roommate profiles (preferences and personal items):
{profile_context}

Historical split patterns (how similar items were split before):
{history_context}

Items to classify:
{items_str}

Rules:
1. PROFILES ARE THE SOURCE OF TRUTH. If a profile says an item is personal, assign it to that person regardless of history.
2. Use history only as supporting evidence when profiles are silent on an item.
3. If unsure, assign as shared.
4. Only assign personal to a user who is active in this order.
5. Return ONLY valid JSON, no explanation.

Return a JSON array like:
[
  {{"item": "item name", "assign_to": "shared"}},
  {{"item": "item name", "assign_to": 36896689}}
]"""


def classify_items(items: list[str], active_user_ids: list[int]) -> list[dict]:
    """
    Returns list of {item, assign_to} where assign_to is "shared" or a splitwise user id (int).
    """
    profiles = _load_profiles()
    results = []
    ambiguous_items = []

    for item in items:
        uid = _profile_match(item, profiles, active_user_ids)
        if uid is not None:
            logger.info("Profile match: '%s' → %s", item, USER_NAMES.get(uid, uid))
            results.append({"item": item, "assign_to": uid})
        else:
            ambiguous_items.append(item)

    if not ambiguous_items:
        return results

    all_profile_chunks = []
    all_history_chunks = []
    for item in ambiguous_items:
        all_profile_chunks.extend(_retrieve(item, "profiles", top_k=3))
        all_history_chunks.extend(_retrieve(item, "history", top_k=3))

    seen = set()
    profile_chunks = [c for c in all_profile_chunks if not (c in seen or seen.add(c))]
    history_chunks = [c for c in all_history_chunks if not (c in seen or seen.add(c))]

    prompt = _build_prompt(ambiguous_items, active_user_ids, profile_chunks[:10], history_chunks[:10])

    response = bedrock.converse(
        modelId="amazon.nova-lite-v1:0",
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )
    raw = response["output"]["message"]["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    llm_assignments = json.loads(raw.strip())

    for a in llm_assignments:
        if a["assign_to"] != "shared":
            a["assign_to"] = int(a["assign_to"])
    results.extend(llm_assignments)

    logger.info("Item assignments: %s", results)
    return results
