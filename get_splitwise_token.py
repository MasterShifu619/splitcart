"""
Run once locally to get a Splitwise OAuth 2.0 bearer token.
Add the printed SPLITWISE_BEARER_TOKEN value to .env
"""
from splitwise import Splitwise

CONSUMER_KEY = input("Consumer Key: ").strip()
CONSUMER_SECRET = input("Consumer Secret: ").strip()

REDIRECT_URI = "https://www.splitwise.com"

sw = Splitwise(CONSUMER_KEY, CONSUMER_SECRET)
auth_url, _ = sw.getOAuth2AuthorizeURL(REDIRECT_URI)

print(f"\nOpen this URL in your browser:\n\n{auth_url}\n")
print("After clicking Authorize, your browser URL bar will briefly show:")
print("  https://www.splitwise.com/?code=XXXXXXXX&state=...")
print("Copy just the code value (between 'code=' and '&state').\n")

code_received = input("Paste the code here: ").strip()

if not code_received:
    print("No code provided.")
    exit(1)

token = sw.getOAuth2AccessToken(code_received, REDIRECT_URI)
print(f"\nAdd to your .env:\nSPLITWISE_BEARER_TOKEN={token['access_token']}")
