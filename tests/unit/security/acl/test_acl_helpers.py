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

``objects_manager`` guards every read / write with ``verify_access(object_type, user, permission)``, so
these tests pin the opt-in rule: no ACL or a deactivated one permits everything, an activated one
permits only what the user's group holds, and a denial raises AccessDeniedError rather than returning a
falsy value the caller might ignore.
"""
from types import SimpleNamespace

import pytest

from cmdb.errors.security import AccessDeniedError
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.helpers import (
    acl_grants_access,
    has_access_control,
    has_type_document_access,
    verify_access,
)
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 2
OTHER_GROUP_ID: int = 7


def _type_with_acl(acl: AccessControlList | None) -> SimpleNamespace:
    """A CmdbType stand-in carrying just the acl property the helpers read."""
    return SimpleNamespace(acl=acl)


def _user(group_id: int = GROUP_ID) -> SimpleNamespace:
    """A CmdbUser stand-in carrying just the group_id the helpers read."""
    return SimpleNamespace(group_id=group_id)


def _acl(activated: bool, includes: dict | None = None) -> AccessControlList:
    """Builds a stored-shape ACL."""
    return AccessControlList.from_data({
        AclKey.ACTIVATED.value: activated,
        AclKey.GROUPS.value: {AclKey.INCLUDES.value: includes or {}},
    })


class TestHasAccessControl:
    """The boolean decision."""

    def test_a_type_without_an_acl_is_open(self) -> None:
        """Access control is opt-in - no ACL means no restriction."""
        assert has_access_control(_type_with_acl(None), _user(), AccessControlPermission.READ) is True

    def test_a_deactivated_acl_is_open(self) -> None:
        """The activated switch turns the whole list off."""
        acl = _acl(activated=False, includes={'2': []})

        assert has_access_control(_type_with_acl(acl), _user(), AccessControlPermission.READ) is True

    def test_an_activated_acl_permits_the_granted_permission(self) -> None:
        """The user's group holds READ."""
        acl = _acl(activated=True, includes={'2': ['READ']})

        assert has_access_control(_type_with_acl(acl), _user(), AccessControlPermission.READ) is True

    def test_an_activated_acl_denies_a_permission_that_is_not_granted(self) -> None:
        """READ does not imply DELETE."""
        acl = _acl(activated=True, includes={'2': ['READ']})

        assert has_access_control(_type_with_acl(acl), _user(), AccessControlPermission.DELETE) is False

    def test_an_activated_acl_denies_another_group(self) -> None:
        """A group with no entry holds nothing."""
        acl = _acl(activated=True, includes={'2': ['READ']})

        assert has_access_control(_type_with_acl(acl), _user(OTHER_GROUP_ID), AccessControlPermission.READ) is False


class TestVerifyAccess:
    """The raising wrapper the managers call."""

    def test_a_permitted_access_returns_none(self) -> None:
        """No exception means the caller may proceed."""
        acl = _acl(activated=True, includes={'2': ['READ']})

        assert verify_access(_type_with_acl(acl), _user(), AccessControlPermission.READ) is None

    def test_a_denied_access_raises(self) -> None:
        """A denial must be impossible to ignore."""
        acl = _acl(activated=True, includes={'2': ['READ']})

        with pytest.raises(AccessDeniedError):
            verify_access(_type_with_acl(acl), _user(), AccessControlPermission.DELETE)

    @pytest.mark.parametrize('user, permission', [
        (None, AccessControlPermission.READ),
        (_user(), None),
        (None, None),
    ])
    def test_without_a_user_or_permission_no_check_runs(self, user, permission) -> None:
        """Internal callers that pass neither are not access-checked (documented behaviour)."""
        acl = _acl(activated=True, includes={'2': []})

        assert verify_access(_type_with_acl(acl), user, permission) is None


class TestAclGrantsAccess:
    """The single expression of the opt-in rule, which the other two helpers delegate to."""

    def test_no_acl_grants(self) -> None:
        """None is the shape a CmdbType that was never given an ACL carries."""
        assert acl_grants_access(None, GROUP_ID, AccessControlPermission.READ) is True

    def test_a_deactivated_acl_grants(self) -> None:
        """The switch is consulted before the groups are."""
        assert acl_grants_access(_acl(activated=False), GROUP_ID, AccessControlPermission.READ) is True

    def test_an_activated_acl_decides_per_group(self) -> None:
        """Only the requesting group's own entry is read."""
        acl = _acl(activated=True, includes={str(GROUP_ID): ['READ']})

        assert acl_grants_access(acl, GROUP_ID, AccessControlPermission.READ) is True
        assert acl_grants_access(acl, OTHER_GROUP_ID, AccessControlPermission.READ) is False

    def test_an_activated_acl_without_the_permission_denies(self) -> None:
        """A group entry that exists but lacks the permission is still a denial."""
        acl = _acl(activated=True, includes={str(GROUP_ID): ['READ']})

        assert acl_grants_access(acl, GROUP_ID, AccessControlPermission.DELETE) is False


class TestHasTypeDocumentAccess:
    """The same decision taken against a raw CmdbType document instead of the model."""

    @staticmethod
    def _type_document(acl_data: dict | None) -> dict:
        """A CmdbType document as it comes out of Mongo; None omits the acl key entirely."""
        document: dict = {'public_id': 10, 'name': 'server'}

        if acl_data is not None:
            document['acl'] = acl_data

        return document

    def test_a_document_without_an_acl_key_is_open(self) -> None:
        """A type saved before ACLs existed carries no acl key at all."""
        assert has_type_document_access(
            self._type_document(None), _user(), AccessControlPermission.READ,
        ) is True

    def test_a_null_acl_is_open(self) -> None:
        """`acl: null` must not be read as an activated empty ACL, which would deny everything."""
        assert has_type_document_access(
            self._type_document(None) | {'acl': None}, _user(), AccessControlPermission.READ,
        ) is True

    def test_a_deactivated_acl_document_is_open(self) -> None:
        """The stored shape the type builder writes when the switch is off."""
        acl_data = {AclKey.ACTIVATED.value: False, AclKey.GROUPS.value: {AclKey.INCLUDES.value: None}}

        assert has_type_document_access(
            self._type_document(acl_data), _user(), AccessControlPermission.READ,
        ) is True

    def test_an_activated_acl_document_decides_per_group(self) -> None:
        """Group keys are stored as strings, which is what the Angular ACL editor writes."""
        acl_data = {
            AclKey.ACTIVATED.value: True,
            AclKey.GROUPS.value: {AclKey.INCLUDES.value: {str(GROUP_ID): ['READ']}},
        }

        assert has_type_document_access(
            self._type_document(acl_data), _user(GROUP_ID), AccessControlPermission.READ,
        ) is True
        assert has_type_document_access(
            self._type_document(acl_data), _user(OTHER_GROUP_ID), AccessControlPermission.READ,
        ) is False

    def test_an_activated_acl_with_no_groups_denies_everyone(self) -> None:
        """Fails closed - the same rule AccessControlList.verify_access applies."""
        acl_data = {AclKey.ACTIVATED.value: True, AclKey.GROUPS.value: {AclKey.INCLUDES.value: {}}}

        assert has_type_document_access(
            self._type_document(acl_data), _user(), AccessControlPermission.READ,
        ) is False

    def test_it_agrees_with_the_model_based_helper(self) -> None:
        """The document and the model path must never disagree - that is the point of the lift."""
        acl_data = {
            AclKey.ACTIVATED.value: True,
            AclKey.GROUPS.value: {AclKey.INCLUDES.value: {str(GROUP_ID): ['READ']}},
        }
        acl = AccessControlList.from_data(acl_data)

        for group_id in (GROUP_ID, OTHER_GROUP_ID):
            assert has_type_document_access(
                self._type_document(acl_data), _user(group_id), AccessControlPermission.READ,
            ) is has_access_control(
                _type_with_acl(acl), _user(group_id), AccessControlPermission.READ,
            )
