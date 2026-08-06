"""Google OAuth endpoints: login, callback, status, disconnect."""
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import httpx

from app.database import get_db
from app.auth import google_oauth
from app.models import UserToken
from app.schemas import AuthStatusOut
from app.config import get_settings
from app.utils.logger import logger

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def _google_oauth_configured() -> bool:
    return (
        bool(settings.google_client_id)
        and bool(settings.google_client_secret)
        and not settings.google_client_id.startswith("your-")
        and not settings.google_client_secret.startswith("your-")
    )


@router.get("/google/login")
def login():
    """Redirects the browser to Google's consent screen."""
    if not _google_oauth_configured():
        return RedirectResponse(
            f"{settings.frontend_url}?connected=false&error=Google+OAuth+is+not+configured+in+backend/.env"
        )
    url = google_oauth.build_auth_url()
    return RedirectResponse(url)


@router.get("/google/reauth")
def reauth(db: Session = Depends(get_db)):
    """Disconnects stale credentials and forces fresh Google consent."""
    if not _google_oauth_configured():
        return RedirectResponse(
            f"{settings.frontend_url}?connected=false&error=Google+OAuth+is+not+configured+in+backend/.env"
        )
    google_oauth.disconnect(db)
    url = google_oauth.build_reauth_url()
    return RedirectResponse(url)


@router.get("/google/callback")
def callback(code: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    """Google redirects here after consent. Exchanges the code or handles an OAuth error."""
    if error:
        logger.error(f"OAuth callback returned error: {error}")
        return RedirectResponse(f"{settings.frontend_url}?connected=false&error={error}")

    if not code:
        logger.error("OAuth callback missing authorization code")
        return RedirectResponse(f"{settings.frontend_url}?connected=false&error=missing_code")

    try:
        creds = google_oauth.exchange_code_for_tokens(code)
        userinfo = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
        ).json()
        email = userinfo.get("email", "unknown")
        if email.strip().lower() != settings.google_allowed_email.strip().lower():
            logger.warning(f"Unauthorized Google login attempt for {email}")
            return RedirectResponse(
                f"{settings.frontend_url}?connected=false&error=unauthorized_email"
            )
        google_oauth.save_credentials(db, creds, email)
        return RedirectResponse(f"{settings.frontend_url}?connected=true")
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        return RedirectResponse(f"{settings.frontend_url}?connected=false&error={e}")


@router.get("/status", response_model=AuthStatusOut)
def status(db: Session = Depends(get_db)):
    token_row = db.query(UserToken).first()
    if not token_row or not token_row.refresh_token:
        return AuthStatusOut(connected=False)
    return AuthStatusOut(connected=True, email=token_row.email, drive_folder_id=token_row.drive_folder_id)


@router.post("/google/disconnect")
def disconnect(db: Session = Depends(get_db)):
    google_oauth.disconnect(db)
    return {"disconnected": True}
