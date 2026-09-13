from pathlib import Path
import re


KERNEL_REF_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _env_value(path: Path, key: str) -> str:
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    raise AssertionError(f"{key} not found in {path}")


def test_promoted_kernel_baseline_is_consistent_across_current_release_surfaces() -> None:
    expected = _env_value(Path(".env.production.example"), "AGENT_KERNEL_REF")
    assert KERNEL_REF_PATTERN.fullmatch(expected)

    for workflow in (
        Path(".github/workflows/ci.yml"),
        Path(".github/workflows/m5.yml"),
    ):
        text = workflow.read_text(encoding="utf-8")
        refs = re.findall(r"ref:\s*([0-9a-f]{40})", text)
        assert refs, f"no pinned Kernel revision found in {workflow}"
        assert set(refs) == {expected}, (
            f"{workflow} pins {sorted(set(refs))}, expected only {expected}"
        )

    staging_ref = _env_value(Path("deploy/m9-staging/.env.example"), "AGENT_KERNEL_REF")
    assert staging_ref == expected
