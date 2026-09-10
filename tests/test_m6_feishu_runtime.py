from __future__ import annotations

import json
from uuid import uuid4

import httpx
from pydantic import SecretStr

from administrative_orchestrator.config import Settings
from administrative_orchestrator.intake.interpretation import (
    InterpretationProfile,
    ModelProvenance,
    ModelRequest,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.providers.feishu_runtime import (
    HttpJsonModelGateway,
    build_feishu_runtime,
)


def test_http_json_model_gateway_preserves_candidate_only_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidate_intent": "onboard employee:1",
                "candidate_facts": [],
            },
        )

    gateway = HttpJsonModelGateway(
        "https://model.invalid/v1/interpret",
        ModelProvenance(
            provider="test-gateway",
            model_identity="test-model",
            model_version="v1",
        ),
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        response = gateway.complete(
            ModelRequest(
                artifact_ref=uuid4(),
                profile=InterpretationProfile(
                    profile_ref="feishu-onboarding-v1",
                    schema_ref="candidate-interpretation-v1",
                    instruction="candidate only",
                ),
                source_text="please onboard employee:1",
            ),
            timeout_seconds=1,
        )
    finally:
        gateway.close()

    assert json.loads(response.raw_output)["candidate_intent"] == "onboard employee:1"
    assert response.provenance.provider == "test-gateway"
    assert requests[0].headers["Authorization"] == "Bearer test-key"
    sent = json.loads(requests[0].content)
    assert sent["profile"]["profile_ref"] == "feishu-onboarding-v1"


def test_feishu_runtime_fails_closed_until_processing_dependencies_exist() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()

    disabled = build_feishu_runtime(
        store,
        Settings(database_url="sqlite+pysqlite:///:memory:"),
    )
    assert disabled is not None
    assert disabled.boundary is None
    assert disabled.pipeline is None
    disabled.close()

    configured = build_feishu_runtime(
        store,
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            feishu_base_url="https://open.feishu.invalid",
            feishu_verification_token=SecretStr("verification-token"),
            feishu_access_token=SecretStr("access-token"),
            intake_model_url="https://model.invalid/v1/interpret",
        ),
    )
    assert configured is not None
    assert configured.boundary is not None
    assert configured.pipeline is not None
    configured.close()
