from dotenv import load_dotenv; load_dotenv()
import os
import json
import voyageai
from pinecone import Pinecone

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "profiles")

voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index(os.environ["PINECONE_INDEX"])


def profile_to_chunks(profile: dict) -> list[dict]:
    name = profile["name"]
    uid = profile["splitwise_id"]
    chunks = []

    if profile.get("personal_items"):
        items = ", ".join(profile["personal_items"])
        chunks.append({
            "id": f"{uid}_personal",
            "text": f"{name} buys these items personally and does not split them: {items}.",
        })

    if profile.get("never_buys"):
        items = ", ".join(profile["never_buys"])
        chunks.append({
            "id": f"{uid}_never",
            "text": f"{name} never buys or consumes: {items}.",
        })

    for i, rule in enumerate(profile.get("split_with_subset", [])):
        items = ", ".join(rule["items"])
        with_ids = rule["with"]
        note = rule.get("note", "")
        chunks.append({
            "id": f"{uid}_subset_{i}",
            "text": f"{name} splits {items} only with users {with_ids}. {note}.",
        })

    if profile.get("notes"):
        chunks.append({
            "id": f"{uid}_notes",
            "text": f"{name}: {profile['notes']}",
        })

    return chunks


def main():
    all_chunks = []
    for fname in os.listdir(PROFILES_DIR):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(PROFILES_DIR, fname)) as f:
            profile = json.load(f)
        chunks = profile_to_chunks(profile)
        all_chunks.extend(chunks)
        print(f"  {profile['name']}: {len(chunks)} chunks")

    texts = [c["text"] for c in all_chunks]
    result = voyage.embed(texts, model="voyage-3", input_type="document")
    embeddings = result.embeddings

    vectors = [
        {
            "id": chunk["id"],
            "values": emb,
            "metadata": {"text": chunk["text"]},
        }
        for chunk, emb in zip(all_chunks, embeddings)
    ]

    index.upsert(vectors=vectors, namespace="profiles")
    print(f"\nUpserted {len(vectors)} chunks into Pinecone namespace 'profiles'")


if __name__ == "__main__":
    main()
