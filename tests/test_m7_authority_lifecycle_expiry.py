from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from administrative_orchestrator.authority import (
    AuthorityError,
    AuthorityRepository,
)
from administrative_orchestrator.authority_lifecycle import AuthorityLifecycleRepository
from administrative_orchestrator.domain import (
    Delegation,
    Principal,
    PrincipalKind,
    RoleAssignment,
)
from administrative_orchestrator.persistence import SqlStore

_BASELINE = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


def _setup():
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    authority = AuthorityRepository(store)
    for principal_id in ('person:departing', 'person:successor'):
        authority.put_principal(
            Principal(
                principal_id=principal_id,
                kind=PrincipalKind.PERSON,
                display_name=principal_id,
            )
        )
    assignment = authority.put_role_assignment(
        RoleAssignment(
            assignment_id=uuid4(),
            principal_id='person:departing',
            role='manager',
            organization_scope='*',
            valid_from=_BASELINE,
            valid_until=None,
        )
    )
    delegation = authority.put_delegation(
        Delegation(
            delegation_id=uuid4(),
            from_principal_id='person:departing',
            to_principal_id='person:successor',
            role='manager',
            organization_scope='*',
            valid_from=_BASELINE,
            valid_until=_BASELINE + timedelta(days=30),
        )
    )
    lifecycle = AuthorityLifecycleRepository(store)
    return store, authority, lifecycle, assignment, delegation


def test_expire_role_assignment_ends_current_authority_and_is_idempotent() -> None:
    _, authority, lifecycle, assignment, _ = _setup()
    before = _BASELINE + timedelta(days=1)
    effective_at = _BASELINE + timedelta(days=10)
    assert 'manager' in authority.roles_for(
        'person:departing', organization_scope='*', at=before
    )

    event = lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='offboarding effective time reached',
        at=effective_at,
    )
    assert event.event_type == 'role_assignment.expired'
    assert event.payload['role'] == 'manager'
    assert event.payload['valid_until'] == effective_at.isoformat()

    replay = lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='offboarding effective time reached',
        at=effective_at,
    )
    assert replay == event
    matching = [
        item for item in lifecycle.list_events() if item.event_id == event.event_id
    ]
    assert len(matching) == 1

    after = effective_at + timedelta(seconds=1)
    assert 'manager' not in authority.roles_for(
        'person:departing', organization_scope='*', at=after
    )
    assert 'manager' in authority.roles_for(
        'person:departing', organization_scope='*', at=before
    )


def test_expire_role_assignment_is_monotonic_and_validates_the_window() -> None:
    _, authority, lifecycle, assignment, _ = _setup()
    late = _BASELINE + timedelta(days=20)
    early = _BASELINE + timedelta(days=10)

    lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='late expiry',
        at=late,
    )
    event = lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='earlier expiry must not extend',
        at=early,
    )
    assert event.payload['valid_until'] == early.isoformat()

    later = lifecycle.expire_role_assignment(
        assignment.assignment_id,
        actor_principal_id='person:admin',
        reason='a later expiry must not extend the window',
        at=_BASELINE + timedelta(days=25),
    )
    assert later.payload['valid_until'] == early.isoformat()
    assert 'manager' not in authority.roles_for(
        'person:departing',
        organization_scope='*',
        at=_BASELINE + timedelta(days=22),
    )

    with pytest.raises(AuthorityError, match='cannot precede'):
        lifecycle.expire_role_assignment(
            assignment.assignment_id,
            actor_principal_id='person:admin',
            reason='before the window',
            at=_BASELINE - timedelta(seconds=1),
        )
    with pytest.raises(AuthorityError, match='does not exist'):
        lifecycle.expire_role_assignment(
            uuid4(),
            actor_principal_id='person:admin',
            reason='missing target',
        )


def test_expire_delegation_ends_delegated_authority() -> None:
    _, authority, lifecycle, _, delegation = _setup()
    before = _BASELINE + timedelta(days=1)
    effective_at = _BASELINE + timedelta(days=5)
    assert 'manager' in authority.roles_for(
        'person:successor', organization_scope='*', at=before
    )

    event = lifecycle.expire_delegation(
        delegation.delegation_id,
        actor_principal_id='person:admin',
        reason='offboarding effective time reached',
        at=effective_at,
    )
    assert event.event_type == 'delegation.expired'
    assert event.payload['to_principal_id'] == 'person:successor'

    after = effective_at + timedelta(seconds=1)
    assert 'manager' not in authority.roles_for(
        'person:successor', organization_scope='*', at=after
    )
    assert 'manager' in authority.roles_for(
        'person:successor', organization_scope='*', at=before
    )


def test_expire_operations_require_a_reason() -> None:
    _, _, lifecycle, assignment, delegation = _setup()
    with pytest.raises(AuthorityError, match='requires a reason'):
        lifecycle.expire_role_assignment(
            assignment.assignment_id,
            actor_principal_id='person:admin',
            reason='   ',
        )
    with pytest.raises(AuthorityError, match='requires a reason'):
        lifecycle.expire_delegation(
            delegation.delegation_id,
            actor_principal_id='person:admin',
            reason='',
        )
