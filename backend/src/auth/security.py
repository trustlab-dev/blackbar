import time
from datetime import timedelta

import jwt
from passlib.context import CryptContext

from src.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, JWT_SECRET

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta = None):
    """Mint a JWT with an ``exp`` claim computed in real UTC (Unix epoch).

    Uses ``time.time()`` directly rather than ``datetime.utcnow()`` so the
    ``exp`` claim is a real Unix epoch regardless of the host timezone.
    PyJWT validates ``exp`` against ``time.time()``; any non-tz-aware
    ``datetime.utcnow().timestamp()`` pattern would silently inflate the
    claim by the local TZ offset on non-UTC hosts (B1).
    """
    to_encode = data.copy()
    delta = expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = int(time.time() + delta.total_seconds())
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
