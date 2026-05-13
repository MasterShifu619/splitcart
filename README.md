# Splitcart

Automatically splits Instacart grocery bills among roommates using Splitwise. No more manually entering receipts.

---

## v1 vs v2

| | v1 | v2 (current) |
|---|---|---|
| **Splitting** | Equal split among all roommates | Smart split — personal items charged to owner, shared items split equally |
| **Notes** | None | Full itemized receipt with per-person breakdown |
| **Intelligence** | None | RAG pipeline: roommate profiles + order history + LLM |
| **Deployment** | Terraform zip | Docker container image on ECR |
| **Cost** | $0/month | ~$1–2/month (Voyage AI + Pinecone free tiers cover light usage) |

---

## How it works (v2)

1. Someone orders groceries on Instacart
2. Delivery confirmation email arrives in shared Gmail inbox
3. Lambda wakes up every 10 minutes, fetches unread emails
4. Parses store, total, card last-4, and **itemized receipt** (item names + prices + tax)
5. RAG pipeline classifies each item as personal (one person) or shared:
   - Deterministic pre-filter checks roommate profile keywords (LaCroix → Mahim, pasta → Varun)
   - Ambiguous items go to Pinecone (retrieves profile + history context) → Bedrock Nova Lite classifies
6. Computes unequal owed amounts: personal items full price to owner + shared items + tax/fee split equally
7. Creates Splitwise expense with correct payer, per-person owed amounts, and annotated notes
8. DynamoDB records the order to prevent duplicates

---

## Architecture

```
Instacart email
      ↓
Gmail forwarding rule → shared inbox
      ↓
EventBridge (every 10 min) → Lambda
      ↓
Gmail API → parse email (store, total, card, items)
      ↓
item_splitter.classify_items()
  ├── profile keyword match (deterministic, fast)
  └── ambiguous items → Voyage AI embed → Pinecone query
                                ↓
                      profile chunks + history chunks
                                ↓
                      AWS Bedrock (Nova Lite) → JSON assignments
      ↓
compute_owed_shares() → unequal split
      ↓
DynamoDB (dedup) → Splitwise API (create expense with notes)
```

**Vector DB namespaces:**
- `profiles` — roommate preferences (personal items, never-buys, dietary habits)
- `history` — past Splitwise expenses (how similar items were split before)

---

## Setup Guide

### Prerequisites

- Python 3.10+
- Docker (for container image builds)
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) configured
- [Terraform](https://developer.hashicorp.com/terraform/install) 1.6+
- A shared Gmail inbox all roommates forward Instacart emails to
- A [Splitwise](https://www.splitwise.com) group with all roommates
- [Voyage AI](https://www.voyageai.com) account (free tier: 50M tokens/month)
- [Pinecone](https://www.pinecone.io) account (free tier: 2 GB storage)

---

### Step 1 — Fork & clone

```bash
git clone https://github.com/<your-username>/splitcart.git
cd splitcart
pip install -r requirements.txt
```

---

### Step 2 — Set up Gmail forwarding

Each roommate who orders groceries needs a Gmail filter to auto-forward Instacart receipts to the shared inbox.

In Gmail: **Settings → Filters → Create new filter**
- From: `orders@instacart.com`
- Action: Forward to `<your-shared-inbox>@gmail.com`

---

### Step 3 — Set up Splitwise app

1. Go to [splitwise.com/apps](https://www.splitwise.com/apps) → **Register your application**
2. Set **Callback URL** to `https://www.splitwise.com`
3. Note your **Consumer Key** and **Consumer Secret**
4. Run the token script:
   ```bash
   python get_splitwise_token.py
   ```
   Authorize in browser → copy the `code` from the redirect URL → paste when prompted → copy the printed `SPLITWISE_BEARER_TOKEN`

**Get your group ID and user IDs:**
```bash
# Group ID is in the URL: splitwise.com/groups/XXXXXXX

# Get user IDs for all roommates:
curl -H "Authorization: Bearer YOUR_BEARER_TOKEN" \
  "https://secure.splitwise.com/api/v3.0/get_group/YOUR_GROUP_ID" | python -m json.tool | grep '"id"'
```

---

### Step 4 — Set up Gmail API

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a new project
2. Enable the **Gmail API**
3. Configure **OAuth consent screen** → External → publish to production (avoids 7-day token expiry)
4. Create credentials → **OAuth 2.0 Client ID** → Desktop app → download as `credentials.json`
5. Run the auth flow:
   ```bash
   python auth_gmail.py
   ```
   Open the printed URL → sign in as shared inbox account → authorize → `token.json` is saved

---

### Step 5 — Set up Voyage AI

1. Sign up at [voyageai.com](https://www.voyageai.com)
2. Get your API key from the dashboard
3. This is used to embed item names and profile text into 1024-dim vectors

---

### Step 6 — Set up Pinecone

1. Sign up at [pinecone.io](https://www.pinecone.io)
2. Create a **Serverless** index named `splitcart` (or any name):
   - Dimensions: `1024`
   - Metric: `cosine`
   - Cloud: `AWS`, Region: `us-east-1`
3. Get your API key from the dashboard

---

### Step 7 — Create roommate profiles

Create `profiles/<splitwise_user_id>.json` for each roommate:

```json
{
  "name": "Alice",
  "splitwise_id": 12345678,
  "personal_items": ["LaCroix", "sparkling water", "pasta", "greek yogurt"],
  "never_buys": ["soda", "ramen"]
}
```

- `personal_items` — items this person always buys for themselves (billed to them 100%)
- `never_buys` — items this person never uses (helps LLM avoid misassignment)

Then embed the profiles into Pinecone:
```bash
VOYAGE_API_KEY=... PINECONE_API_KEY=... PINECONE_INDEX=splitcart python embed_profiles.py
```

---

### Step 8 — (Optional) Seed history from past expenses

If you have past Splitwise expense data, embed it to improve classification:
```bash
python dump_expenses.py > dump_expenses_output.txt  # export history
VOYAGE_API_KEY=... PINECONE_API_KEY=... PINECONE_INDEX=splitcart python embed_history.py
```

---

### Step 9 — Configure environment

Create `infra/terraform.tfvars`:
```hcl
splitwise_consumer_key    = "..."
splitwise_consumer_secret = "..."
splitwise_bearer_token    = "..."
splitwise_group_id        = "..."
splitwise_user_ids        = "uid1,uid2,uid3"
card_to_user              = "1234:uid1,5678:uid2"
voyage_api_key            = "..."
pinecone_api_key          = "..."
pinecone_index            = "splitcart"
```

**`card_to_user`** — map each roommate's card last-4 digits to their Splitwise user ID. Check a past Instacart email for the card ending shown (e.g. `Visa ending in 4321`).

**`ALLOWED_STORES`** — edit in `lambda_function.py` to match your household's stores.

---

### Step 10 — Deploy to AWS (container image)

Splitcart v2 uses a Docker container image to stay within Lambda's size limits.

**Build and push:**
```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1

# Create ECR repo (first time only)
aws ecr create-repository --repository-name splitcart --region $AWS_REGION

# Build and push
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker buildx build --platform linux/amd64 --provenance=false \
  -t $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/splitcart:latest \
  --push .
```

**Deploy infrastructure:**
```bash
cd infra
terraform init
terraform apply
```

This creates:
- DynamoDB table (`processed_orders`)
- Lambda function (`splitcart`) — container image
- EventBridge rule (fires every 10 minutes)
- IAM roles (Lambda + DynamoDB + Bedrock)

**Update Lambda to use container image** (first deploy after switching from zip):
```bash
aws lambda update-function-code \
  --function-name splitcart \
  --image-uri $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/splitcart:latest \
  --region $AWS_REGION
```

**To redeploy after code changes:**
```bash
# Rebuild and push (same commands above), then:
aws lambda update-function-code \
  --function-name splitcart \
  --image-uri $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/splitcart:latest \
  --region $AWS_REGION
```

---

### Step 11 — Test

```bash
aws lambda invoke --function-name splitcart --region us-east-1 /tmp/out.json && cat /tmp/out.json
```

Expected: `{"processed": 1, "skipped": 0, "failed": 0}`

Check Splitwise — expense should appear with itemized notes and unequal split amounts.

---

## Customization

| What | Where |
|---|---|
| Stores to process | `ALLOWED_STORES` in `lambda_function.py` |
| Roommate profiles | `profiles/<user_id>.json` |
| Poll frequency | `schedule_expression` in `infra/eventbridge.tf` |
| LLM model | `modelId` in `item_splitter.py` |

---

## Re-authentication

**Gmail:** Re-run `python auth_gmail.py` → new `token.json` → rebuild and push container image

**Splitwise:** Re-run `python get_splitwise_token.py` → update `SPLITWISE_BEARER_TOKEN` in `terraform.tfvars` → `terraform apply`

---

## Cost

| Service | Free tier | Splitcart usage | Cost |
|---|---|---|---|
| Lambda | 1M requests/month | ~4,320/month | $0 |
| DynamoDB | 25 GB + 25 WCU/RCU | < 1 MB | $0 |
| EventBridge | 14M events/month | ~4,320/month | $0 |
| Bedrock (Nova Lite) | None | ~$0.0002 per order | ~$0.01/month |
| Voyage AI | 50M tokens/month | ~50K tokens/month | $0 |
| Pinecone | 2 GB storage | < 10 MB | $0 |

**Total: ~$0/month** at typical household usage (Bedrock cost is negligible)

---

## License

MIT
