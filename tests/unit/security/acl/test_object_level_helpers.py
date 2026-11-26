# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for the object-level and "some objects" helpers of ``security.acl.helpers`` (phase 9, R23, R25) - the
engine stood in

Pinned: ``object_access_allowed`` asks ``can`` with the states per permission (READ / DELETE the stored object, UPDATE
before = after, CREATE after) and refuses when it refuses; ``verify_object_access`` raises then, and checks nothing
without a user or a permission; ``type_reachable_for`` / ``has_type_document_reach`` ask ``type_reachable`` and refuse
a Type without an id; ``verify_type_reach`` raises for an unreachable Type
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework import access_engine
from cmdb.models.access_model import ScopeOperation
from cmdb.security.acl import helpers
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

DOCUMENT: dict[str, Any] = {'public_id': 5, 'type_id': 11, 'fields': []}
USER: Any = MagicMock()


@pytest.fixture(name='can')
def fixture_can(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The engine's decision, allowing"""
    decision = MagicMock(return_value=SimpleNamespace(allowed=True))
    monkeypatch.setattr(access_engine, 'can', decision)

    return decision


@pytest.mark.parametrize('permission, operation, before, after', [
    (AccessControlPermission.READ, ScopeOperation.VIEW, DOCUMENT, None),
    (AccessControlPermission.DELETE, ScopeOperation.DELETE, DOCUMENT, None),
    (AccessControlPermission.UPDATE, ScopeOperation.EDIT, DOCUMENT, DOCUMENT),
    (AccessControlPermission.CREATE, ScopeOperation.CREATE, None, DOCUMENT),
], ids=['read', 'delete', 'update', 'create'])
def test_object_access_asks_can_with_the_states(can: MagicMock, permission: AccessControlPermission,
                                                operation: ScopeOperation, before: Any, after: Any) -> None:
    """The states each permission is judged on"""
    assert helpers.object_access_allowed(DOCUMENT, USER, permission)
    can.assert_called_once_with(USER, operation, before, after)


def test_a_refused_object_raises(can: MagicMock) -> None:
    """verify_object_access"""
    can.return_value = SimpleNamespace(allowed=False)

    with pytest.raises(AccessDeniedError):
        helpers.verify_object_access(DOCUMENT, USER, AccessControlPermission.READ)


@pytest.mark.parametrize('user, permission', [(None, AccessControlPermission.READ), (USER, None)],
                         ids=['no-user', 'no-permission'])
def test_an_internal_caller_is_not_judged(can: MagicMock, user: Any, permission: Any) -> None:
    """Nothing asked"""
    helpers.verify_object_access(DOCUMENT, user, permission)

    can.assert_not_called()


def test_type_reach(monkeypatch: pytest.MonkeyPatch) -> None:
    """type_reachable asked; a Type without an id refused; verify_type_reach raises"""
    reachable = MagicMock(return_value=False)
    monkeypatch.setattr(access_engine, 'type_reachable', reachable)

    assert not helpers.type_reachable_for(11, USER, AccessControlPermission.READ)
    assert not helpers.has_type_document_reach({}, USER, AccessControlPermission.READ)
    reachable.assert_called_once_with(USER, [ScopeOperation.VIEW], 11)

    with pytest.raises(AccessDeniedError):
        helpers.verify_type_reach(SimpleNamespace(public_id=11), USER, AccessControlPermission.UPDATE)
