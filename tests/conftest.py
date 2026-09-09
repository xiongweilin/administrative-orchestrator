from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _bounded_dbos_destroy(monkeypatch):
    """Make integration-test DBOS teardown wait for active workflows to quiesce.

    DBOS.destroy() defaults to a zero-second workflow completion wait.  The
    PostgreSQL restart lane destroys and recreates the singleton in one test,
    so returning immediately can leave the notification/recovery background
    machinery alive while the test drops its temporary system database.  That
    turns an otherwise-passing test into a process-exit hang.

    Production code is not changed: this fixture only applies to the explicit
    PostgreSQL/DBOS integration lane and preserves the normal DBOS destroy API
    for all other tests.
    """
    if os.getenv("ADMIN_RUN_DBOS_INTEGRATION") != "1":
        yield
        return

    from dbos import DBOS

    original_destroy = DBOS.destroy

    def destroy(*args, **kwargs):
        kwargs.setdefault("workflow_completion_timeout_sec", 10)
        return original_destroy(*args, **kwargs)

    monkeypatch.setattr(DBOS, "destroy", staticmethod(destroy))
    yield
