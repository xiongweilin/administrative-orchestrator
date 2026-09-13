from pathlib import Path


HEX_DIGITS = frozenset("0123456789abcdef")


def _env_value(path: Path, key: str) -> str:
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    raise AssertionError(f"{key} not found in {path}")


def _is_full_git_sha(value: str) -> bool:
    return len(value) == 40 and set(value) <= HEX_DIGITS


def test_promoted_kernel_baseline_is_consistent_across_current_release_surfaces() -> None:
    expected = _env_value(Path(".env.production.example"), "AGENT_KERNEL_REF")
    assert _is_full_git_sha(expected)

    for workflow in (
        Path(".github/workflows/ci.yml"),
        Path(".github/workflows/m5.yml"),
    ):
        refs = {
            line.split("ref:", 1)[1].strip()
            for line in workflow.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("ref:")
            and _is_full_git_sha(line.split("ref:", 1)[1].strip())
        }
        assert refs, f"no pinned Kernel revision found in {workflow}"
        assert refs == {expected}, f"{workflow} pins {sorted(refs)}, expected only {expected}"
