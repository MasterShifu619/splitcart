import os
import json
import logging
from typing import Iterator

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
SHARED_INBOX = os.environ["GMAIL_SHARED_INBOX"]
CREDENTIALS_PATH = os.environ.get("GMAIL_CREDENTIALS_JSON", "credentials.json")
TOKEN_PATH = os.environ.get("GMAIL_TOKEN_JSON", "token.json")
BUNDLED_TOKEN_PATH = "/var/task/token.json"


def _ensure_token_writable() -> None:
    """On Lambda cold start, copy bundled token.json to writable /tmp path."""
    if not os.path.exists(TOKEN_PATH) and os.path.exists(BUNDLED_TOKEN_PATH):
        import shutil
        shutil.copy(BUNDLED_TOKEN_PATH, TOKEN_PATH)


def _get_credentials() -> Credentials:
    _ensure_token_writable()
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=False)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def _build_service():
    return build("gmail", "v1", credentials=_get_credentials())


def fetch_unread_instacart_emails() -> Iterator[dict]:
    """
    Yield full Gmail message dicts for unread Instacart order emails.
    Marks each message as read after yielding.
    """
    service = _build_service()
    query = 'subject:"Instacart" is:unread'

    response = (
        service.users()
        .messages()
        .list(userId=SHARED_INBOX, q=query, maxResults=50)
        .execute()
    )
    messages = response.get("messages", [])
    logger.info("Found %d unread Instacart emails", len(messages))

    for stub in messages:
        msg_id = stub["id"]
        full_msg = (
            service.users()
            .messages()
            .get(userId=SHARED_INBOX, id=msg_id, format="full")
            .execute()
        )
        yield full_msg
        # Mark read so we don't reprocess on next poll (DynamoDB is primary guard)
        service.users().messages().modify(
            userId=SHARED_INBOX,
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
