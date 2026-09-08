from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, String, Uuid, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class SandboxBase(DeclarativeBase):
    pass


class RealizedEffectRow(SandboxBase):
    __tablename__ = "realized_effect"

    effect_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    target_system: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    realized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SandboxStore:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite"):
            path_text = database_url.split("///", 1)[-1]
            if path_text and path_text != ":memory:":
                Path(path_text).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                database_url,
                future=True,
                connect_args={"check_same_thread": False},
            )
        else:
            self.engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def init_schema(self) -> None:
        SandboxBase.metadata.create_all(self.engine)


class ApplyEffectBody(BaseModel):
    target_system: str
    operation: str
    subject_ref: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplyEffectResponse(BaseModel):
    status: str = "succeeded"
    provider_ref: str


class ObservationResponse(BaseModel):
    found: bool = True
    target_system: str
    operation: str
    subject_ref: str
    provider_ref: str
    state: dict[str, Any]
    digest: str
    observed_at: datetime


settings = get_settings()
store = SandboxStore(settings.sandbox_database_url)
store.init_schema()
app = FastAPI(title="Administrative Authoritative Sandbox", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.put("/v1/effects/{effect_id}", response_model=ApplyEffectResponse)
def apply_effect(effect_id: UUID, body: ApplyEffectBody) -> ApplyEffectResponse:
    provider_ref = f"sandbox:{effect_id}"
    state = {
        "target_system": body.target_system,
        "operation": body.operation,
        "subject_ref": body.subject_ref,
        "payload": body.payload,
        "active": True,
    }
    digest = canonical_digest(state)
    with store.sessions.begin() as db:
        existing = db.get(RealizedEffectRow, effect_id)
        if existing is not None:
            if (
                existing.target_system != body.target_system
                or existing.operation != body.operation
                or existing.subject_ref != body.subject_ref
                or existing.payload_json != body.payload
            ):
                raise HTTPException(
                    status_code=409,
                    detail="effect id already realized with different semantics",
                )
            return ApplyEffectResponse(provider_ref=provider_ref)
        db.add(
            RealizedEffectRow(
                effect_id=effect_id,
                target_system=body.target_system,
                operation=body.operation,
                subject_ref=body.subject_ref,
                payload_json=body.payload,
                state_json=state,
                digest=digest,
                realized_at=utcnow(),
            )
        )
    return ApplyEffectResponse(provider_ref=provider_ref)


@app.get("/v1/effects/{effect_id}", response_model=ObservationResponse)
def observe_effect(effect_id: UUID) -> ObservationResponse:
    with store.sessions() as db:
        row = db.get(RealizedEffectRow, effect_id)
        if row is None:
            raise HTTPException(status_code=404, detail="effect not found")
        return ObservationResponse(
            target_system=row.target_system,
            operation=row.operation,
            subject_ref=row.subject_ref,
            provider_ref=f"sandbox:{effect_id}",
            state=row.state_json,
            digest=row.digest,
            observed_at=row.realized_at,
        )
