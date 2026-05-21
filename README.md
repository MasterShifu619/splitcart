# Splitcart

Automatically splits Instacart grocery bills among roommates using Splitwise. No more manually entering receipts.

**How it works:** Someone orders groceries on Instacart → delivery confirmation email arrives → Splitcart parses the total and card used → creates a Splitwise expense split equally among all roommates → correct person is marked as payer automatically.

Runs on AWS Lambda + EventBridge (polls every 10 minutes). Fits entirely within the AWS free tier — **$0/month**.

---

## Architecture

```
Instacart email
      ↓
Gmail forwarding rule → shared inbox (groceries.split@gmail.com)
      ↓
EventBridge (every 10 min) → Lambda
      ↓
Gmail API → parse email (store, total, card)
      ↓
DynamoDB (dedup check) → Splitwise API (create expense)
```
### Version 2

<img width="1061" height="864" alt="image" src="https://github.com/user-attachments/assets/9a9ddb60-9bbe-4c3b-957b-2f726cbdece0" />

### Version 1

<img width="720" height="560" alt="image" src="https://github.com/user-attachments/assets/b2b239ed-4531-42fc-943f-604eaf6c5a7a" />

---

## Setup Guide

### Prerequisites

- Python 3.10+
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html)
- [Terraform](https://developer.hashicorp.com/terraform/install) 1.6+
- A shared Gmail inbox all roommates forward Instacart emails to
- A [Splitwise](https://www.splitwise.com) group with all roommates

---

### Step 1 — Fork & clone

```bash
git clone https://github.com/<your-username>/splitcart.git
cd splitcart
pip install -r requirements.txt
```

---

### Step 2 — Set up Gmail forwarding

Each roommate who orders groceries needs a Gmail filter to auto-forward Instacart receipts to your shared inbox.

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
   Authorize in your browser → copy the `code` from the redirect URL → paste when prompted → copy the printed `SPLITWISE_BEARER_TOKEN`

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
3. Configure **OAuth consent screen** → External → add your shared inbox as a test user
4. Create credentials → **OAuth 2.0 Client ID** → Desktop app → download as `credentials.json` and place it in the project root
5. Run the auth flow:
   ```bash
   python auth_gmail.py
   ```
   Open the printed URL in your browser → sign in as your shared inbox account → authorize → `token.json` is saved

---

### Step 5 — Configure environment

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

```env
SPLITWISE_CONSUMER_KEY=...
SPLITWISE_CONSUMER_SECRET=...
SPLITWISE_BEARER_TOKEN=...
SPLITWISE_GROUP_ID=...
SPLITWISE_USER_IDS=uid1,uid2,uid3,uid4

# card last 4 digits → Splitwise user ID
# format: "XXXX:userid,YYYY:userid"
CARD_TO_USER=1234:userid1,5678:userid2

GMAIL_CREDENTIALS_JSON=credentials.json
GMAIL_TOKEN_JSON=token.json
GMAIL_SHARED_INBOX=your-shared-inbox@gmail.com

AWS_REGION=us-east-1
DYNAMODB_TABLE=processed_orders
```

**Finding card last 4 digits:** Check a past Instacart receipt email — it shows e.g. `Visa ending in 4321`. Map each roommate's card to their Splitwise user ID.

**Allowed stores:** Edit `ALLOWED_STORES` in `lambda_function.py` to match your household's stores.

---

### Step 6 — Deploy to AWS

Configure AWS credentials:
```bash
aws configure
```

Create `infra/terraform.tfvars`:
```hcl
splitwise_consumer_key    = "..."
splitwise_consumer_secret = "..."
splitwise_bearer_token    = "..."
splitwise_group_id        = "..."
splitwise_user_ids        = "uid1,uid2,uid3,uid4"
card_to_user              = "1234:uid1,5678:uid2"
```

Deploy:
```bash
cd infra
terraform init
terraform apply
```

This creates:
- DynamoDB table (`processed_orders`)
- Lambda function (`splitcart`)
- EventBridge rule (fires every 10 minutes)

---

### Step 7 — Test

```bash
aws lambda invoke --function-name splitcart --region us-east-1 /tmp/out.json && cat /tmp/out.json
```

Expected: `{"processed": 1, "skipped": 0, "failed": 0}`

Check your Splitwise group — the expense should appear.

---

## Customization

| What | Where |
|---|---|
| Stores to process | `ALLOWED_STORES` in `lambda_function.py` |
| Number of roommates | `SPLITWISE_USER_IDS` in `.env` / `terraform.tfvars` |
| Poll frequency | `schedule_expression` in `infra/eventbridge.tf` |
| Expense description | `expense.description` in `splitwise_client.py` |

---

## Re-authentication

**Gmail:** Re-run `python auth_gmail.py` → new `token.json` → `terraform apply`

**Splitwise:** Re-run `python get_splitwise_token.py` → update `SPLITWISE_BEARER_TOKEN` in `terraform.tfvars` → `terraform apply`

---

## Cost

Everything runs within the AWS free tier:

| Service | Free tier | Splitcart usage |
|---|---|---|
| Lambda | 1M requests/month | ~4,320/month |
| DynamoDB | 25 GB storage + 25 WCU/RCU | < 1 MB |
| EventBridge | 14M events/month | ~4,320/month |

**Total: $0/month**

---

## License

MIT
