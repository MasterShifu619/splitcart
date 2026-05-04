"""
Run once to generate token.json for Gmail OAuth.
Works in WSL — opens URL manually, catches redirect via local HTTP server.
"""
import json
import threading
import urllib.parse
import http.server
from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
PORT = 8080
REDIRECT_URI = f"http://localhost:{PORT}/"

auth_code = None
done = threading.Event()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorization complete. You can close this tab.")
            done.set()
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


flow = Flow.from_client_secrets_file(
    "credentials.json", scopes=SCOPES, redirect_uri=REDIRECT_URI
)
auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

server = http.server.HTTPServer(("0.0.0.0", PORT), CallbackHandler)
t = threading.Thread(target=server.serve_forever)
t.daemon = True
t.start()

print(f"\nOpen this URL in your browser (Windows):\n\n{auth_url}\n")
print("Waiting for authorization...")
done.wait(timeout=120)

if not auth_code:
    print("Timed out. Re-run and authorize faster.")
    exit(1)

flow.fetch_token(code=auth_code)
creds = flow.credentials

with open("token.json", "w") as f:
    json.dump({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }, f)

print("token.json saved!")
server.shutdown()
