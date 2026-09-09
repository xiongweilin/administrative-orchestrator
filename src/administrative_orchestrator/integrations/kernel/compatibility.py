from dataclasses import dataclass

EXPECTED_CATALOG_VERSION = "portable-runtime-contracts-v1"
EXPECTED_OWNER = "portable-runtime/contracts"
EXPECTED_RUNTIME_PROTOCOL = "2.0"
EXPECTED_PERSISTENT_RESPONSIBILITY = "persistent-responsibility-v1"
EXPECTED_DOMAIN_RESPONSIBILITY_PROPOSAL = "domain-responsibility-proposal-v1"
EXPECTED_RESPONSIBILITY_WORK_ADMISSION = "responsibility-work-admission-v1"
EXPECTED_BOUNDED_DOMAIN_EFFECT_EXECUTION = "bounded-domain-effect-execution-v1"
EXPECTED_BOUNDED_DOMAIN_EFFECT_RECOVERY = "bounded-domain-effect-recovery-v1"
EXPECTED_BOUNDED_DOMAIN_EFFECT_RESOLUTION = "bounded-domain-effect-resolution-v1"
EXPECTED_DOMAIN_EFFECT_VERIFICATION_EVIDENCE_VIEW = (
    "domain-effect-verification-evidence-view-v1"
)


class KernelCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KernelContractIdentity:
    catalog_version: str
    owner: str
    runtime_protocol: str
    persistent_responsibility_contract: str
    domain_responsibility_proposal_contract: str
    responsibility_work_admission_contract: str | None = None
    bounded_domain_effect_execution_contract: str | None = None
    bounded_domain_effect_recovery_contract: str | None = None
    bounded_domain_effect_resolution_view: str | None = None
    domain_effect_verification_evidence_view: str | None = None


def validate_kernel_catalog(
    raw: dict[str, object],
    *,
    require_work_admission: bool = False,
    require_domain_effect_execution: bool = False,
    require_domain_effect_recovery: bool = False,
    require_domain_effect_evidence: bool = False,
) -> KernelContractIdentity:
    try:
        contracts = raw["contracts"]
        if not isinstance(contracts, dict):
            raise TypeError("contracts must be an object")
        persistent_responsibility = contracts["persistent_responsibility"]
        if not isinstance(persistent_responsibility, dict):
            raise TypeError("persistent_responsibility must be an object")
        domain_responsibility_proposal = contracts["domain_responsibility_proposal"]
        if not isinstance(domain_responsibility_proposal, dict):
            raise TypeError("domain_responsibility_proposal must be an object")
        persistent = persistent_responsibility["current"]
        domain_proposal = domain_responsibility_proposal["current"]

        work_admission_contract: str | None = None
        work_admission = contracts.get("responsibility_work_admission")
        if work_admission is not None:
            if not isinstance(work_admission, dict):
                raise TypeError("responsibility_work_admission must be an object")
            work_admission_contract = str(work_admission["current"])

        execution_contract: str | None = None
        bounded_execution = contracts.get("bounded_domain_effect_execution")
        if bounded_execution is not None:
            if not isinstance(bounded_execution, dict):
                raise TypeError("bounded_domain_effect_execution must be an object")
            execution_contract = str(bounded_execution["current"])

        recovery_contract: str | None = None
        resolution_view: str | None = None
        bounded_recovery = contracts.get("bounded_domain_effect_recovery")
        if bounded_recovery is not None:
            if not isinstance(bounded_recovery, dict):
                raise TypeError("bounded_domain_effect_recovery must be an object")
            recovery_contract = str(bounded_recovery["current"])
            raw_resolution = bounded_recovery.get("resolution")
            if raw_resolution is not None:
                resolution_view = str(raw_resolution)

        evidence_view: str | None = None
        views = raw.get("views")
        if views is not None:
            if not isinstance(views, dict):
                raise TypeError("views must be an object")
            domain_evidence = views.get("domain_effect_verification_evidence")
            if domain_evidence is not None:
                if not isinstance(domain_evidence, dict):
                    raise TypeError("domain_effect_verification_evidence view must be an object")
                evidence_view = str(domain_evidence["current"])

        identity = KernelContractIdentity(
            catalog_version=str(raw["catalog_version"]),
            owner=str(raw["owner"]),
            runtime_protocol=str(raw["runtime_protocol"]),
            persistent_responsibility_contract=str(persistent),
            domain_responsibility_proposal_contract=str(domain_proposal),
            responsibility_work_admission_contract=work_admission_contract,
            bounded_domain_effect_execution_contract=execution_contract,
            bounded_domain_effect_recovery_contract=recovery_contract,
            bounded_domain_effect_resolution_view=resolution_view,
            domain_effect_verification_evidence_view=evidence_view,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelCompatibilityError("kernel contract catalog is structurally incomplete") from exc

    mismatches: list[str] = []
    if identity.catalog_version != EXPECTED_CATALOG_VERSION:
        mismatches.append(
            f"catalog_version={identity.catalog_version!r}, expected {EXPECTED_CATALOG_VERSION!r}"
        )
    if identity.owner != EXPECTED_OWNER:
        mismatches.append(f"owner={identity.owner!r}, expected {EXPECTED_OWNER!r}")
    if identity.runtime_protocol != EXPECTED_RUNTIME_PROTOCOL:
        mismatches.append(
            f"runtime_protocol={identity.runtime_protocol!r}, expected {EXPECTED_RUNTIME_PROTOCOL!r}"
        )
    if identity.persistent_responsibility_contract != EXPECTED_PERSISTENT_RESPONSIBILITY:
        mismatches.append(
            "persistent_responsibility="
            f"{identity.persistent_responsibility_contract!r}, "
            f"expected {EXPECTED_PERSISTENT_RESPONSIBILITY!r}"
        )
    if (
        identity.domain_responsibility_proposal_contract
        != EXPECTED_DOMAIN_RESPONSIBILITY_PROPOSAL
    ):
        mismatches.append(
            "domain_responsibility_proposal="
            f"{identity.domain_responsibility_proposal_contract!r}, "
            f"expected {EXPECTED_DOMAIN_RESPONSIBILITY_PROPOSAL!r}"
        )
    if (
        identity.responsibility_work_admission_contract is not None
        and identity.responsibility_work_admission_contract
        != EXPECTED_RESPONSIBILITY_WORK_ADMISSION
    ):
        mismatches.append(
            "responsibility_work_admission="
            f"{identity.responsibility_work_admission_contract!r}, "
            f"expected {EXPECTED_RESPONSIBILITY_WORK_ADMISSION!r}"
        )
    if (
        identity.bounded_domain_effect_execution_contract is not None
        and identity.bounded_domain_effect_execution_contract
        != EXPECTED_BOUNDED_DOMAIN_EFFECT_EXECUTION
    ):
        mismatches.append(
            "bounded_domain_effect_execution="
            f"{identity.bounded_domain_effect_execution_contract!r}, "
            f"expected {EXPECTED_BOUNDED_DOMAIN_EFFECT_EXECUTION!r}"
        )
    if (
        identity.bounded_domain_effect_recovery_contract is not None
        and identity.bounded_domain_effect_recovery_contract
        != EXPECTED_BOUNDED_DOMAIN_EFFECT_RECOVERY
    ):
        mismatches.append(
            "bounded_domain_effect_recovery="
            f"{identity.bounded_domain_effect_recovery_contract!r}, "
            f"expected {EXPECTED_BOUNDED_DOMAIN_EFFECT_RECOVERY!r}"
        )
    if (
        identity.bounded_domain_effect_resolution_view is not None
        and identity.bounded_domain_effect_resolution_view
        != EXPECTED_BOUNDED_DOMAIN_EFFECT_RESOLUTION
    ):
        mismatches.append(
            "bounded_domain_effect_resolution="
            f"{identity.bounded_domain_effect_resolution_view!r}, "
            f"expected {EXPECTED_BOUNDED_DOMAIN_EFFECT_RESOLUTION!r}"
        )
    if (
        identity.domain_effect_verification_evidence_view is not None
        and identity.domain_effect_verification_evidence_view
        != EXPECTED_DOMAIN_EFFECT_VERIFICATION_EVIDENCE_VIEW
    ):
        mismatches.append(
            "domain_effect_verification_evidence="
            f"{identity.domain_effect_verification_evidence_view!r}, "
            f"expected {EXPECTED_DOMAIN_EFFECT_VERIFICATION_EVIDENCE_VIEW!r}"
        )
    if (
        require_work_admission
        and identity.responsibility_work_admission_contract
        != EXPECTED_RESPONSIBILITY_WORK_ADMISSION
    ):
        mismatches.append(
            "responsibility_work_admission is required for admission mode or cutover mode: "
            f"expected {EXPECTED_RESPONSIBILITY_WORK_ADMISSION!r}"
        )
    if (
        require_domain_effect_execution
        and identity.bounded_domain_effect_execution_contract
        != EXPECTED_BOUNDED_DOMAIN_EFFECT_EXECUTION
    ):
        mismatches.append(
            "bounded_domain_effect_execution is required for cutover mode: "
            f"expected {EXPECTED_BOUNDED_DOMAIN_EFFECT_EXECUTION!r}"
        )
    if require_domain_effect_recovery and (
        identity.bounded_domain_effect_recovery_contract
        != EXPECTED_BOUNDED_DOMAIN_EFFECT_RECOVERY
        or identity.bounded_domain_effect_resolution_view
        != EXPECTED_BOUNDED_DOMAIN_EFFECT_RESOLUTION
    ):
        mismatches.append(
            "bounded_domain_effect_recovery/resolution are required for cutover mode: "
            f"expected {EXPECTED_BOUNDED_DOMAIN_EFFECT_RECOVERY!r} + "
            f"{EXPECTED_BOUNDED_DOMAIN_EFFECT_RESOLUTION!r}"
        )
    if (
        require_domain_effect_evidence
        and identity.domain_effect_verification_evidence_view
        != EXPECTED_DOMAIN_EFFECT_VERIFICATION_EVIDENCE_VIEW
    ):
        mismatches.append(
            "domain_effect_verification_evidence is required for cutover mode: "
            f"expected {EXPECTED_DOMAIN_EFFECT_VERIFICATION_EVIDENCE_VIEW!r}"
        )
    if mismatches:
        raise KernelCompatibilityError("incompatible agent-kernel contracts: " + "; ".join(mismatches))
    return identity


class HttpKernelContractProbe:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 3.0,
        require_work_admission: bool = False,
        require_domain_effect_execution: bool = False,
        require_domain_effect_recovery: bool = False,
        require_domain_effect_evidence: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.require_work_admission = require_work_admission
        self.require_domain_effect_execution = require_domain_effect_execution
        self.require_domain_effect_recovery = require_domain_effect_recovery
        self.require_domain_effect_evidence = require_domain_effect_evidence

    def fetch_identity(self) -> KernelContractIdentity:
        import httpx

        try:
            response = httpx.get(
                f"{self.base_url}/v1/contracts",
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KernelCompatibilityError(f"agent-kernel contract probe unavailable: {exc}") from exc
        if not isinstance(payload, dict):
            raise KernelCompatibilityError("agent-kernel contract catalog must be a JSON object")
        return validate_kernel_catalog(
            payload,
            require_work_admission=self.require_work_admission,
            require_domain_effect_execution=self.require_domain_effect_execution,
            require_domain_effect_recovery=self.require_domain_effect_recovery,
            require_domain_effect_evidence=self.require_domain_effect_evidence,
        )


__all__ = [
    "EXPECTED_BOUNDED_DOMAIN_EFFECT_EXECUTION",
    "EXPECTED_BOUNDED_DOMAIN_EFFECT_RECOVERY",
    "EXPECTED_BOUNDED_DOMAIN_EFFECT_RESOLUTION",
    "EXPECTED_CATALOG_VERSION",
    "EXPECTED_DOMAIN_EFFECT_VERIFICATION_EVIDENCE_VIEW",
    "EXPECTED_DOMAIN_RESPONSIBILITY_PROPOSAL",
    "EXPECTED_OWNER",
    "EXPECTED_PERSISTENT_RESPONSIBILITY",
    "EXPECTED_RESPONSIBILITY_WORK_ADMISSION",
    "EXPECTED_RUNTIME_PROTOCOL",
    "HttpKernelContractProbe",
    "KernelCompatibilityError",
    "KernelContractIdentity",
    "validate_kernel_catalog",
]
