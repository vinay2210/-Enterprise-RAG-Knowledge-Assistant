"""
Google OAuth2 flow (login / callback / refresh).

Design decision: this is a single-user local tool (per the assignment scope:
one 'AI Knowledge Base' folder). We persist exactly one UserToken row.
Swapping to multi-user just means keying UserToken by a real user id instead
of always fetching row #1 - the rest of the app doesn't need to change.
"""
from datetime import datetime, timedelta

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import UserToken
from app.utils.logger import logger

settings = get_settings()

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_auth_url() -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=settings.google_redirect_uri)
    auth_url, _ = flow.authorization_url(
        access_type="offline",       # required to get a refresh_token
        include_granted_scopes="true",
        prompt="consent select_account",  # force account chooser + refresh consent each login
    )
    return auth_url

def build_reauth_url() -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=settings.google_redirect_uri)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent select_account",
    )
    return auth_url


def exchange_code_for_tokens(code: str) -> Credentials:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=settings.google_redirect_uri)
    flow.fetch_token(code=code)
    return flow.credentials


def save_credentials(db: Session, creds: Credentials, email: str) -> UserToken:
    token_row = db.query(UserToken).first()
    if token_row is None:
        token_row = UserToken(email=email)
        db.add(token_row)

    token_row.email = email
    token_row.access_token = creds.token
    token_row.refresh_token = creds.refresh_token or token_row.refresh_token
    token_row.token_expiry = creds.expiry
    token_row.drive_folder_id = token_row.drive_folder_id
    db.commit()
    db.refresh(token_row)
    logger.info(f"Saved Google credentials for {email}")
    return token_row


def get_valid_credentials(db: Session) -> Credentials | None:
    """Returns a Credentials object, refreshing the access token if expired."""
    token_row = db.query(UserToken).first()
    if not token_row or not token_row.refresh_token:
        return None

    creds = Credentials(
        token=token_row.access_token,
        refresh_token=token_row.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )

    if not creds.valid:
        try:
            creds.refresh(GoogleRequest())
            token_row.access_token = creds.token
            token_row.token_expiry = creds.expiry
            db.commit()
            logger.info("Refreshed Google access token")
        except Exception as e:
            logger.error(f"Failed to refresh Google token: {e}")
            return None

    return creds


def disconnect(db: Session) -> None:
    db.query(UserToken).delete()
    db.commit()
