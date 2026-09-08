from pathlib import Path

DBOS_ALLOWED = {
    Path("src/administrative_orchestrator/worker.py"),
    Path("src/administrative_orchestrator/workflows/bootstrap.py"),
    Path("src/administrative_orchestrator/workflows/definitions.py"),
    Path("src/administrative_orchestrator/workflows/relay.py"),
}


def test_dbos_imports_stay_at_durable_orchestration_boundary() -> None:
    root = Path("src/administrative_orchestrator")
    violations: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if ("from dbos import" in text or "import dbos" in text) and path not in DBOS_ALLOWED:
            violations.append(str(path))
    assert violations == []
