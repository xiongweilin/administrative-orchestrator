from dataclasses import dataclass

EXPECTED_CATALOG_VERSION = "portable-runtime-contracts-v1"
EXPECTED_OWNER = "portable-runtime/contracts"
EXPECTED_RUNTIME_PROTOCOL = "2.0"
EXPECTED_PERSISTENT_RESPONSIBILITY = "persistent-responsibility-v1"
EXPECTED_DOMAIN_RESPONSIBILITY_PROPOSAL = "domain-responsibility-proposal-v1"
EXPECTED_RESPONSIBILITY_WORK_ADMISSION = "responsibility-work-admission-v1"


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


def validate_kernel_catalog(
    raw: dict[str, object],
    *,
    require_work_admission: bool = False,
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
        identity = KernelContractIdentity(
            catalog_version=str(raw["catalog_version"]),
            owner=str(raw["owner"]),
            runtime_protocol=str(raw["runtime_protocol"]),
            persistent_responsibility_contract=str(persistent),
            domain_responsibility_proposal_contract=str(domain_proposal),
            responsibility_work_admission_contract=work_admission_contract,
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
        require_work_admission
        and identity.responsibility_work_admission_contract
        != EXPECTED_RESPONSIBILITY_WORK_ADMISSION
    ):
        mismatches.append(
            "responsibility_work_admission is required for admission mode: "
            f"expected {EXPECTED_RESPONSIBILITY_WORK_ADMISSION!r}"
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.require_work_admission = require_work_admission

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
        )


__all__ = [
    "EXPECTED_CATALOG_VERSION",
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
