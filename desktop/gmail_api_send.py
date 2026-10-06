#!/usr/bin/env python3
"""Send email via Gmail API using local OAuth token (apex-gmail)."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
DEFAULT_TOKEN = Path.home() / ".config" / "apex-gmail" / "token.json"


def send_gmail_api(
    *,
    address: str,
    subject: str,
    body: str,
    attachments: list[Path],
    token_path: Path | None = None,
) -> str:
    path = token_path or DEFAULT_TOKEN
    if not path.exists():
        raise FileNotFoundError(
            f"找不到 Gmail token：{path}\n請先完成 OAuth（uvx mcp-google-gmail auth）。"
        )
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Gmail token 無效，請重新授權。")

    msg = EmailMessage()
    msg["To"] = address
    msg["From"] = address
    msg["Subject"] = subject
    msg.set_content(body, charset="utf-8")
    for p in attachments:
        if p.exists():
            msg.add_attachment(
                p.read_bytes(),
                maintype="text",
                subtype="plain",
                filename=p.name,
            )

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service = build("gmail", "v1", credentials=creds)
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return str(result.get("id", ""))
