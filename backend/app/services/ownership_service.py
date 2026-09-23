"""Opaque browser capability used to authorize access to one persisted plan."""
from hashlib import sha256
import hmac
import re

from ..config import get_settings
from ..errors import PlanAccessDenied

OWNER_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def hash_owner_token(token: str) -> str:
    if not OWNER_TOKEN_PATTERN.fullmatch(token):
        raise PlanAccessDenied()
    return sha256(token.encode("ascii")).hexdigest()


def require_owner_hash(token: str | None) -> str | None:
    if token is None:
        if get_settings().require_plan_owner_token:
            raise PlanAccessDenied()
        return None
    return hash_owner_token(token)


def authorize_owner(stored_hash: str | None, token: str | None) -> None:
    if stored_hash is None:
        if get_settings().require_plan_owner_token:
            raise PlanAccessDenied()
        return
    if token is None:
        raise PlanAccessDenied()
    supplied_hash = hash_owner_token(token)
    if not hmac.compare_digest(stored_hash, supplied_hash):
        raise PlanAccessDenied()
