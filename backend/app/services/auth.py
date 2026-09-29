import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import get_db
from app.models.user import User

settings = Settings()

bearer_scheme = HTTPBearer()
optional_bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


# Use bcrypt directly: passlib 1.7.4 is incompatible with bcrypt >= 4.1.
# bcrypt only considers the first 72 bytes of a password, so truncate
# explicitly (newer bcrypt raises instead of truncating silently).
def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_reset_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_reset_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hex)``. The raw token goes in the email link;
    only the hash is persisted, so a leaked DB row can't be replayed."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_reset_token(raw)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


async def _load_user_from_token(token: str, db: AsyncSession) -> Optional[User]:
    """Decode a JWT and load its user, or return None if invalid/unknown."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await _load_user_from_token(credentials.credentials, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Like get_current_user but returns None instead of raising when there is
    no (or an invalid) bearer token — for endpoints that vary by auth state."""
    if credentials is None:
        return None
    return await _load_user_from_token(credentials.credentials, db)


async def require_librarian(user: User = Depends(get_current_user)) -> User:
    """A signed-in librarian: 401 for anonymous (via get_current_user), 403 for a reader."""
    if not user.is_librarian:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Librarians only.")
    return user
