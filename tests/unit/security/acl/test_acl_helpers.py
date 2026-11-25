# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.security.acl.helpers - the access decision the managers actually call

``acl_grants_access`` is the type ACL's own frozen reading; its tests pin the opt-in rule: no ACL or a deactivated
one permits everything, an activated one permits only what the user's groups hold.

``has_access_control``, ``has_type_document_access`` and ``verify_access`` ask the access engine (``type_allowed``).
Their tests let the engine answer from the very Types they build (``decide_by_type_acls``), so the ACL-shaped
expectations still hold, and pin what is the helpers' own: a Type without an int ``public_id`` is refused, the engine
is asked with the permission's scope operation, and a denial raises AccessDeniedError rather than returning a falsy
value the caller might ignore.
"""
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.errors.security import AccessDeniedError
from cmdb.framework import access_engine
from cmdb.models.access_model import ScopeOperation
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.helpers import (
    acl_grants_access,
    has_access_control,
    has_type_document_access,
    type_allowed,
    verify_access,
)
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.type_acl_engine_stub import decide_by_type_acls
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 2
OTHER_GROUP_ID: int = 7
THIRD_GROUP_ID: int = 9
TYPE_ID: int = 10
USER_ID: int = 41
NOT_AN_ID: str = '10'


def _acl_data(activated: bool, includes: dict | None = None) -> dict[str, Any]:
    """Builds a stored-shape ACL document."""
    return {AclKey.ACTIVATED.value: activated, AclKey.GROUPS.value: {AclKey.INCLUDES.value: includes or {}}}


def _acl(activated: bool, includes: dict | None = None) -> AccessControlList:
    """Builds a stored-shape ACL."""
    return AccessControlList.from_data(_acl_data(activated, includes))


def _type_with_acl(monkeypatch: pytest.MonkeyPatch, acl_data: dict[str, Any] | None) -> SimpleNamespace:
    """
    A CmdbType stand-in carrying the public_id and acl - the engine answering from that acl

    Args:
        monkeypatch (pytest.MonkeyPatch): The test's monkeypatch
        acl_data (dict[str, Any] | None): The stored acl; None for a Type without one

    Returns:
        SimpleNamespace: The Type stand-in
    """
    decide_by_type_acls(monkeypatch, [{TypeSchemaKey.PUBLIC_ID.value: TYPE_ID, TypeSchemaKey.ACL.value: acl_data}])

    return SimpleNamespace(public_id=TYPE_ID, acl=None if acl_data is None else AccessControlList.from_data(acl_data))


def _type_document(monkeypatch: pytest.MonkeyPatch, acl_data: Any, with_acl_key: bool = True) -> dict[str, Any]:
    """
    A CmdbType document as it comes out of Mongo - the engine answering from its acl

    Args:
        monkeypatch (pytest.MonkeyPatch): The test's monkeypatch
        acl_data (Any): The stored acl
        with_acl_key (bool): False omits the acl key entirely

    Returns:
        dict[str, Any]: The Type document
    """
    document: dict[str, Any] = {TypeSchemaKey.PUBLIC_ID.value: TYPE_ID, TypeSchemaKey.NAME.value: 'server'}

    if with_acl_key:
        document[TypeSchemaKey.ACL.value] = acl_data

    decide_by_type_acls(monkeypatch, [document])

    return document


def _user(group_id: int = GROUP_ID) -> SimpleNamespace:
    """A CmdbUser stand-in in one group, carrying just the group_ids the engine stand-in reads."""
    return SimpleNamespace(public_id=USER_ID, group_ids=[group_id])


class TestHasAccessControl:
    """The boolean decision."""

    def test_a_type_without_an_acl_is_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Access control is opt-in - no ACL means no restriction."""
        assert has_access_control(_type_with_acl(monkeypatch, None), _user(), AccessControlPermission.READ) is True

    def test_a_deactivated_acl_is_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The activated switch turns the whole list off."""
        target = _type_with_acl(monkeypatch, _acl_data(activated=False, includes={'2': []}))

        assert has_access_control(target, _user(), AccessControlPermission.READ) is True

    def test_an_activated_acl_permits_the_granted_permission(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The user's group holds READ."""
        target = _type_with_acl(monkeypatch, _acl_data(activated=True, includes={'2': ['READ']}))

        assert has_access_control(target, _user(), AccessControlPermission.READ) is True

    def test_an_activated_acl_denies_a_permission_that_is_not_granted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """READ does not imply DELETE."""
        target = _type_with_acl(monkeypatch, _acl_data(activated=True, includes={'2': ['READ']}))

        assert has_access_control(target, _user(), AccessControlPermission.DELETE) is False

    def test_an_activated_acl_denies_another_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A group with no entry holds nothing."""
        target = _type_with_acl(monkeypatch, _acl_data(activated=True, includes={'2': ['READ']}))

        assert has_access_control(target, _user(OTHER_GROUP_ID), AccessControlPermission.READ) is False

    def test_a_user_in_several_groups_is_passed_whole(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """has_access_control hands the engine the user with every group"""
        target = _type_with_acl(monkeypatch, _acl_data(activated=True, includes={str(GROUP_ID): ['READ']}))
        user = SimpleNamespace(public_id=USER_ID, group_ids=[OTHER_GROUP_ID, GROUP_ID])

        assert has_access_control(target, user, AccessControlPermission.READ) is True

    @pytest.mark.parametrize('public_id', [None, NOT_AN_ID, True])
    def test_a_type_without_an_int_public_id_is_refused(self, monkeypatch: pytest.MonkeyPatch, public_id: Any) -> None:
        """Fail closed: a Type that cannot be named is never taken for an unrestricted one"""
        _type_with_acl(monkeypatch, None)

        assert has_access_control(
            SimpleNamespace(public_id=public_id, acl=None), _user(), AccessControlPermission.READ,
        ) is False


class TestTypeAllowed:
    """The one question every helper asks the access engine"""

    @pytest.mark.parametrize('permission, operation', [
        (AccessControlPermission.READ, ScopeOperation.VIEW),
        (AccessControlPermission.CREATE, ScopeOperation.CREATE),
        (AccessControlPermission.UPDATE, ScopeOperation.EDIT),
        (AccessControlPermission.DELETE, ScopeOperation.DELETE),
    ])
    @pytest.mark.parametrize('answer', [True, False])
    def test_the_engine_is_asked_with_the_operation_and_answers(
            self, monkeypatch: pytest.MonkeyPatch, permission: AccessControlPermission,
            operation: ScopeOperation, answer: bool) -> None:
        """The user, the permission's scope operation and the Type go to ``type_allows``; its answer is returned"""
        calls: list[tuple[Any, Any, Any]] = []

        def type_allows(user: Any, operations: Any, type_id: Any) -> bool:
            """Records the question and answers as told"""
            calls.append((user, operations, type_id))
            return answer

        monkeypatch.setattr(access_engine, 'type_allows', type_allows)
        user = _user()

        assert type_allowed(TYPE_ID, user, permission) is answer
        assert calls == [(user, [operation], TYPE_ID)]

    @pytest.mark.parametrize('type_id', [None, NOT_AN_ID, True, False, float(TYPE_ID)])
    def test_no_int_id_is_refused_without_asking(self, monkeypatch: pytest.MonkeyPatch, type_id: Any) -> None:
        """A missing or non-int id (a bool included) is refused before the engine is asked"""
        def type_allows(*_: Any) -> bool:
            """Must not be reached"""
            raise AssertionError('the engine was asked')

        monkeypatch.setattr(access_engine, 'type_allows', type_allows)

        assert type_allowed(type_id, _user(), AccessControlPermission.READ) is False


class TestVerifyAccess:
    """The raising wrapper the managers call."""

    def test_a_permitted_access_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No exception means the caller may proceed."""
        target = _type_with_acl(monkeypatch, _acl_data(activated=True, includes={'2': ['READ']}))

        assert verify_access(target, _user(), AccessControlPermission.READ) is None

    def test_a_denied_access_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A denial must be impossible to ignore."""
        target = _type_with_acl(monkeypatch, _acl_data(activated=True, includes={'2': ['READ']}))

        with pytest.raises(AccessDeniedError):
            verify_access(target, _user(), AccessControlPermission.DELETE)

    def test_a_type_without_a_public_id_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fail closed: an unnamed Type is refused, even with no acl"""
        _type_with_acl(monkeypatch, None)

        with pytest.raises(AccessDeniedError):
            verify_access(SimpleNamespace(public_id=None, acl=None), _user(), AccessControlPermission.READ)

    @pytest.mark.parametrize('user, permission', [
        (None, AccessControlPermission.READ),
        (_user(), None),
        (None, None),
    ])
    def test_without_a_user_or_permission_no_check_runs(
            self, monkeypatch: pytest.MonkeyPatch, user: Any, permission: Any) -> None:
        """Internal callers that pass neither are not access-checked (documented behaviour)."""
        target = _type_with_acl(monkeypatch, _acl_data(activated=True, includes={'2': []}))

        assert verify_access(target, user, permission) is None


class TestAclGrantsAccess:
    """The type ACL's own frozen reading of the opt-in rule."""

    def test_no_acl_grants(self) -> None:
        """None is the shape a CmdbType that was never given an ACL carries."""
        assert acl_grants_access(None, [GROUP_ID], AccessControlPermission.READ) is True

    def test_a_deactivated_acl_grants(self) -> None:
        """The switch is consulted before the groups are."""
        assert acl_grants_access(_acl(activated=False), [GROUP_ID], AccessControlPermission.READ) is True

    def test_an_activated_acl_decides_per_group(self) -> None:
        """Only the requesting group's own entry is read."""
        acl = _acl(activated=True, includes={str(GROUP_ID): ['READ']})

        assert acl_grants_access(acl, [GROUP_ID], AccessControlPermission.READ) is True
        assert acl_grants_access(acl, [OTHER_GROUP_ID], AccessControlPermission.READ) is False

    def test_an_activated_acl_without_the_permission_denies(self) -> None:
        """A group entry that exists but lacks the permission is still a denial."""
        acl = _acl(activated=True, includes={str(GROUP_ID): ['READ']})

        assert acl_grants_access(acl, [GROUP_ID], AccessControlPermission.DELETE) is False

    def test_one_granting_group_is_enough(self) -> None:
        """The groups combine: a user in a denied and a granted group is granted"""
        acl = _acl(activated=True, includes={str(GROUP_ID): ['READ']})

        assert acl_grants_access(acl, [OTHER_GROUP_ID, GROUP_ID], AccessControlPermission.READ) is True

    def test_no_granting_group_denies(self) -> None:
        """Several groups none of which holds the permission are still denied"""
        acl = _acl(activated=True, includes={str(GROUP_ID): ['READ'], str(OTHER_GROUP_ID): ['CREATE']})

        assert acl_grants_access(acl, [OTHER_GROUP_ID, THIRD_GROUP_ID], AccessControlPermission.READ) is False

    def test_no_groups_deny_an_activated_acl(self) -> None:
        """Fail closed - the listing criteria's reading"""
        assert acl_grants_access(_acl(activated=True), [], AccessControlPermission.READ) is False

    def test_no_groups_still_pass_a_deactivated_acl(self) -> None:
        """The switch is consulted first"""
        assert acl_grants_access(_acl(activated=False), [], AccessControlPermission.READ) is True


class TestHasTypeDocumentAccess:
    """The same decision taken against a raw CmdbType document instead of the model."""

    def test_a_document_without_an_acl_key_is_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A type saved before ACLs existed carries no acl key at all."""
        document = _type_document(monkeypatch, None, with_acl_key=False)

        assert has_type_document_access(document, _user(), AccessControlPermission.READ) is True

    def test_a_null_acl_is_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`acl: null` must not be read as an activated empty ACL, which would deny everything."""
        document = _type_document(monkeypatch, None)

        assert has_type_document_access(document, _user(), AccessControlPermission.READ) is True

    def test_a_deactivated_acl_document_is_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The stored shape the type builder writes when the switch is off."""
        acl_data = {AclKey.ACTIVATED.value: False, AclKey.GROUPS.value: {AclKey.INCLUDES.value: None}}
        document = _type_document(monkeypatch, acl_data)

        assert has_type_document_access(document, _user(), AccessControlPermission.READ) is True

    def test_an_activated_acl_document_decides_per_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Group keys are stored as strings, which is what the Angular ACL editor writes."""
        document = _type_document(monkeypatch, _acl_data(activated=True, includes={str(GROUP_ID): ['READ']}))

        assert has_type_document_access(document, _user(GROUP_ID), AccessControlPermission.READ) is True
        assert has_type_document_access(document, _user(OTHER_GROUP_ID), AccessControlPermission.READ) is False

    def test_an_activated_acl_with_no_groups_denies_everyone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fails closed - the same rule AccessControlList.verify_access applies."""
        document = _type_document(monkeypatch, _acl_data(activated=True))

        assert has_type_document_access(document, _user(), AccessControlPermission.READ) is False

    def test_a_key_that_is_no_group_id_grants_nobody_and_reads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A drifted key does not fail the read; the group keys beside it still decide - as the listing filter does"""
        document = _type_document(
            monkeypatch, _acl_data(activated=True, includes={'admin': ['READ'], str(GROUP_ID): ['READ']}),
        )

        assert has_type_document_access(document, _user(GROUP_ID), AccessControlPermission.READ) is True
        assert has_type_document_access(document, _user(OTHER_GROUP_ID), AccessControlPermission.READ) is False

    def test_it_agrees_with_the_model_based_helper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The document and the model path must never disagree - both name the Type by its public_id."""
        acl_data = _acl_data(activated=True, includes={str(GROUP_ID): ['READ']})
        document = _type_document(monkeypatch, acl_data)
        target = SimpleNamespace(public_id=TYPE_ID, acl=AccessControlList.from_data(acl_data))

        for group_id in (GROUP_ID, OTHER_GROUP_ID):
            assert has_type_document_access(
                document, _user(group_id), AccessControlPermission.READ,
            ) is has_access_control(target, _user(group_id), AccessControlPermission.READ)

    @pytest.mark.parametrize('public_id', [None, NOT_AN_ID])
    def test_a_document_without_an_int_public_id_is_refused(
            self, monkeypatch: pytest.MonkeyPatch, public_id: Any) -> None:
        """Fail closed: a document read without its public_id (a narrow projection) never passes as unrestricted"""
        _type_document(monkeypatch, None, with_acl_key=False)
        document: dict[str, Any] = {TypeSchemaKey.NAME.value: 'server'}

        if public_id is not None:
            document[TypeSchemaKey.PUBLIC_ID.value] = public_id

        assert has_type_document_access(document, _user(), AccessControlPermission.READ) is False
