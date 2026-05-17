"""
Cognito JWT 인증 모듈.

JWKS를 캐싱하여 id_token 서명을 검증하고 UserCtx를 반환한다.
AUTH_MODE=header일 때는 이 모듈을 사용하지 않음.
"""

import os
import time
import urllib.request
import json
from typing import Optional

from fastapi import HTTPException, Header
from jose import jwt, JWTError

from api.users import UserCtx


REGION = os.getenv("COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))
USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
CLIENT_ID = os.getenv("COGNITO_APP_CLIENT_ID", "")
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"

_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0
JWKS_TTL = 3600  # 1 hour


def _fetch_jwks() -> dict:
    with urllib.request.urlopen(JWKS_URL, timeout=5) as resp:
        return json.loads(resp.read())


def _get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    now = time.time()
    if not _jwks_cache or (now - _jwks_fetched_at > JWKS_TTL):
        _jwks_cache = _fetch_jwks()
        _jwks_fetched_at = now
    return _jwks_cache


def _get_signing_key(token: str) -> dict:
    headers = jwt.get_unverified_headers(token)
    kid = headers.get("kid")
    jwks = _get_jwks()
    for key in jwks.get("keys", []):
        if key["kid"] == kid:
            return key
    raise HTTPException(status_code=401, detail="JWT signing key not found")


def verify_jwt(token: str) -> UserCtx:
    """id_token을 검증하고 UserCtx를 반환한다."""
    try:
        key = _get_signing_key(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            issuer=ISSUER,
            options={"verify_at_hash": False},
        )
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    if claims.get("token_use") != "id":
        raise HTTPException(status_code=401, detail="Not an id_token")

    groups = claims.get("cognito:groups") or []
    team_id = groups[0] if groups else "default"
    role = claims.get("custom:role", "member")

    return UserCtx(
        user_id=claims["sub"],
        team_id=team_id,
        role=role,
    )


def get_authenticated_user(
    authorization: Optional[str] = Header(default=None),
) -> UserCtx:
    """FastAPI Depends — Authorization: Bearer <token> 헤더에서 UserCtx 추출."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[7:]
    return verify_jwt(token)
