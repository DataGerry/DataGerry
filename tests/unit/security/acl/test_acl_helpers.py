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
from cmdb.security.acl.helpers import has_access_control, verify_access
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
