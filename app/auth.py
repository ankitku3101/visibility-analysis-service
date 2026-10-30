"""Role comes only from the bearer token. Nothing in the request body can change it."""
import hmac

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.errors import AppError

# auto_error=False: we raise our own JSON 401. HTTPBearer also adds the "Authorize" button to /docs.
bearer = HTTPBearer(auto_error=False)


def _same(a: str, b: str) -> bool:
    # Compare bytes: compare_digest raises TypeError on non-ASCII str, which would be a 500.
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def current_actor(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if creds is None or not creds.credentials:
        raise AppError(401, "unauthorized", "Missing bearer token.")
    settings = get_settings()
    if _same(creds.credentials, settings.analyst_token):
        return "analyst"
    if _same(creds.credentials, settings.reviewer_token):
        return "reviewer"
    raise AppError(401, "unauthorized", "Unknown token.")


def require_role(*roles: str):
    def check(actor: str = Depends(current_actor)) -> str:
        if actor not in roles:
            raise AppError(403, "forbidden", f"This action needs role: {', '.join(roles)}.", {"your_role": actor})
        return actor

    return check
