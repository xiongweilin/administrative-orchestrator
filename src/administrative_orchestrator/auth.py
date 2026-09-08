from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError

from .authority import AuthorityRepository
from .config import Settings
from .domain import Principal
from .persistence import SqlStore


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    principal: Principal
    auth_mode: str
    external_subject: str

    @property
    def principal_id(self) -> str:
        return self.principal.principal_id


class Authenticator:
    def __init__(self, store: SqlStore, settings: Settings) -> None:
        self.repository = AuthorityRepository(store)
        self.settings = settings

    def authenticate(self, request: Request) -> AuthenticatedPrincipal:
        mode = self.settings.auth_mode.strip().lower()
        if mode == "development":
            return self._authenticate_development(request)
        if mode == "jwt":
            return self._authenticate_jwt(request)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="unsupported authentication mode",
        )

    def _authenticate_development(self, request: Request) -> AuthenticatedPrincipal:
        principal_id = request.headers.get("X-Principal-ID", "").strip()
        if not principal_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-Principal-ID is required in development auth mode",
            )
        principal = self.repository.get_principal(principal_id)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="development principal is not registered in the authority plane",
            )
        return AuthenticatedPrincipal(
            principal=principal,
            auth_mode="development",
            external_subject=principal_id,
        )

    def _authenticate_jwt(self, request: Request) -> AuthenticatedPrincipal:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token is required",
            )
        if not self.settings.jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="JWT authentication is not configured",
            )
        token = header.removeprefix("Bearer ").strip()
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=["HS256"],
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                options={"require": ["sub", "iat", "exp"]},
            )
        except InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            ) from exc

        subject = str(claims.get("sub", "")).strip()
        principal = self.repository.resolve_identity(
            provider=self.settings.jwt_issuer,
            external_subject=subject,
        )
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="authenticated identity is not currently bound to an active principal",
            )
        return AuthenticatedPrincipal(
            principal=principal,
            auth_mode="jwt",
            external_subject=subject,
        )


__all__ = ["AuthenticatedPrincipal", "Authenticator"]
