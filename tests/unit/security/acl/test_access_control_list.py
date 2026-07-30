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
Unit tests for the AccessControlList / AccessControlListSection / GroupACL trio

Pure tests (dicts, sets and an enum - no Mongo, no Flask). The emphasis is the access decision and the
storage format both sides of the wire agree on: permissions are the STRING values ('READ' …), which is
what the stored document holds, what the Angular ACL editor sends, and what the aggregation stage in
acl/builder.py matches with ``$all: [permission.value]``.

Pins the four fixes of 2026-07-30: granting to a key the section does not know yet works at all (it
raised TypeError from instantiating a typing alias), grant and verify agree (grant stored the enum
member while verify compared its value, so a freshly granted permission read back as denied), an ACL
without a groups section denies instead of raising, and revoking is idempotent.
"""
import json

import pytest

from typing import Any

from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.access_control_list_section import AccessControlListSection
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.group_acl import GroupACL
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 2
OTHER_GROUP_ID: int = 3
UNKNOWN_GROUP_ID: int = 99


def _stored_acl(includes: dict | None = None, activated: bool = True) -> AccessControlList:
    """Builds an ACL the way it arrives from the database (string keys, lists of permission values)."""
    return AccessControlList.from_data({
        AclKey.ACTIVATED.value: activated,
        AclKey.GROUPS.value: {AclKey.INCLUDES.value: includes if includes is not None else {'2': ['READ']}},
    })


class _PlainSection(AccessControlListSection[int]):
    """A minimal section that does NOT override `includes`, so the abstract base's own accessors run."""

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "_PlainSection":
        """Builds the section straight from the includes mapping."""
        return cls(data.get(AclKey.INCLUDES.value, {}))

    @classmethod
    def to_json(cls, section: "AccessControlListSection[int]") -> dict:
        """Serialises through the shared helper."""
        return {AclKey.INCLUDES.value: cls._serialise_includes(section)}


# -------------------------------------------------------------------------------------------------------------------- #
#                                        AccessControlListSection (base class)                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSectionBaseClass:
    """The behaviour every section inherits, exercised through a section that adds nothing."""

    def test_includes_defaults_to_an_empty_mapping(self) -> None:
        """A section built without data starts empty rather than None."""
        assert _PlainSection().includes == {}

    def test_includes_returns_what_was_set(self) -> None:
        """The base property is a plain accessor - keys are NOT coerced here (GroupACL does that)."""
        section = _PlainSection({'2': ['READ']})

        assert section.includes == {'2': ['READ']}

    def test_a_non_dict_include_structure_raises(self) -> None:
        """The base setter is the type guard."""
        with pytest.raises(TypeError):
            _PlainSection('not-a-dict')

    def test_the_mutators_work_on_the_inherited_accessors(self) -> None:
        """grant / revoke / verify need nothing from a subclass."""
        section = _PlainSection()

        section.grant_access(GROUP_ID, AccessControlPermission.READ)
        assert section.verify_access(GROUP_ID, AccessControlPermission.READ) is True

        section.revoke_access(GROUP_ID, AccessControlPermission.READ)
        assert section.verify_access(GROUP_ID, AccessControlPermission.READ) is False

    def test_the_abstract_methods_must_be_implemented(self) -> None:
        """The base class cannot be instantiated without from_data / to_json."""
        with pytest.raises(TypeError):
            AccessControlListSection()  # pylint: disable=abstract-class-instantiated

    @pytest.mark.parametrize('method_name', ['from_data', 'to_json'])
    def test_the_abstract_stubs_raise_not_implemented(self, method_name: str) -> None:
        """A subclass that delegates to the base instead of implementing it gets a clear error."""
        with pytest.raises(NotImplementedError):
            getattr(AccessControlListSection, method_name)({})

    def test_update_entry_replaces_a_keys_permissions(self) -> None:
        """The low-level setter used when a whole permission set is assigned at once."""
        section = _PlainSection({GROUP_ID: {'READ'}})

        section._update_entry(GROUP_ID, {'UPDATE'})  # pylint: disable=protected-access

        assert section.includes == {GROUP_ID: {'UPDATE'}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            AccessControlPermission                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAccessControlPermission:
    """The enum's values are the strings every other party uses."""

    @pytest.mark.parametrize('permission, expected', [
        (AccessControlPermission.CREATE, 'CREATE'),
        (AccessControlPermission.READ, 'READ'),
        (AccessControlPermission.UPDATE, 'UPDATE'),
        (AccessControlPermission.DELETE, 'DELETE'),
    ])
    def test_the_value_is_the_member_name(self, permission: AccessControlPermission, expected: str) -> None:
        """The Angular enum and the stored documents carry exactly these strings."""
        assert permission.value == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      GroupACL                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGroupACL:
    """The one concrete ACL section."""

    def test_string_keys_are_coerced_to_int(self) -> None:
        """A stored ACL has string keys; a CmdbUser's group_id is an int."""
        section = GroupACL.from_data({AclKey.INCLUDES.value: {'2': ['READ']}})

        assert section.includes == {2: ['READ']}

    def test_from_data_without_includes_is_empty(self) -> None:
        """An ACL that never got a group entry is simply empty."""
        assert GroupACL.from_data({}).includes == {}

    def test_a_non_dict_include_structure_raises(self) -> None:
        """The section only accepts a mapping."""
        with pytest.raises(TypeError):
            GroupACL(['not', 'a', 'dict'])

    def test_to_json_returns_string_keys_and_sorted_lists(self) -> None:
        """Serialisation reproduces the stored wire format."""
        section = GroupACL({GROUP_ID: {'UPDATE', 'READ'}})

        assert GroupACL.to_json(section) == {AclKey.INCLUDES.value: {'2': ['READ', 'UPDATE']}}

    def test_to_json_is_json_serialisable_after_a_grant(self) -> None:
        """A section mutated in memory holds a set - it still has to be storable."""
        section = GroupACL({})
        section.grant_access(GROUP_ID, AccessControlPermission.READ)

        assert json.dumps(GroupACL.to_json(section))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  grant_access                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGrantAccess:
    """Granting a permission - and the guarantee that verify_access then agrees."""

    def test_granting_to_an_unknown_key_creates_the_entry(self) -> None:
        """The first grant for a group used to raise TypeError."""
        section = GroupACL({})

        section.grant_access(GROUP_ID, AccessControlPermission.READ)

        assert section.includes == {GROUP_ID: {'READ'}}

    def test_a_granted_permission_verifies(self) -> None:
        """grant and verify agree (grant stored the member, verify compared the value)."""
        section = GroupACL({})

        section.grant_access(GROUP_ID, AccessControlPermission.UPDATE)

        assert section.verify_access(GROUP_ID, AccessControlPermission.UPDATE) is True

    def test_granting_on_a_stored_section_keeps_the_existing_permissions(self) -> None:
        """A section loaded from the database carries a list; adding to it must not lose entries."""
        acl = _stored_acl({'2': ['READ']})

        acl.grant_access(GROUP_ID, AccessControlPermission.UPDATE)

        assert acl.verify_access(GROUP_ID, AccessControlPermission.READ) is True
        assert acl.verify_access(GROUP_ID, AccessControlPermission.UPDATE) is True

    def test_granting_twice_changes_nothing(self) -> None:
        """Idempotent."""
        section = GroupACL({})

        section.grant_access(GROUP_ID, AccessControlPermission.READ)
        section.grant_access(GROUP_ID, AccessControlPermission.READ)

        assert section.includes == {GROUP_ID: {'READ'}}

    def test_granting_does_not_touch_another_group(self) -> None:
        """One group's permissions are its own."""
        section = GroupACL({OTHER_GROUP_ID: ['DELETE']})

        section.grant_access(GROUP_ID, AccessControlPermission.READ)

        assert section.verify_access(OTHER_GROUP_ID, AccessControlPermission.DELETE) is True
        assert section.verify_access(OTHER_GROUP_ID, AccessControlPermission.READ) is False

    def test_a_section_holding_enum_members_is_normalised(self) -> None:
        """Older in-memory code stored members; a grant normalises the entry to string values."""
        section = GroupACL({GROUP_ID: {AccessControlPermission.READ}})

        section.grant_access(GROUP_ID, AccessControlPermission.UPDATE)

        assert section.includes == {GROUP_ID: {'READ', 'UPDATE'}}
        assert section.verify_access(GROUP_ID, AccessControlPermission.READ) is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 revoke_access                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRevokeAccess:
    """Revoking is the idempotent mirror of granting."""

    def test_revoking_a_granted_permission_removes_it(self) -> None:
        """The happy path."""
        acl = _stored_acl({'2': ['READ', 'UPDATE']})

        acl.revoke_access(GROUP_ID, AccessControlPermission.UPDATE)

        assert acl.verify_access(GROUP_ID, AccessControlPermission.UPDATE) is False
        assert acl.verify_access(GROUP_ID, AccessControlPermission.READ) is True

    def test_revoking_twice_is_a_noop(self) -> None:
        """A permission that is already gone stays gone, without raising."""
        acl = _stored_acl({'2': ['READ']})

        acl.revoke_access(GROUP_ID, AccessControlPermission.READ)
        acl.revoke_access(GROUP_ID, AccessControlPermission.READ)

        assert acl.verify_access(GROUP_ID, AccessControlPermission.READ) is False

    def test_revoking_a_permission_that_was_never_granted_is_a_noop(self) -> None:
        """It used to raise ValueError."""
        section = GroupACL({GROUP_ID: ['READ']})

        section.revoke_access(GROUP_ID, AccessControlPermission.DELETE)

        assert section.includes == {GROUP_ID: {'READ'}}

    def test_revoking_from_an_unknown_key_is_a_noop(self) -> None:
        """It used to raise KeyError."""
        section = GroupACL({})

        section.revoke_access(UNKNOWN_GROUP_ID, AccessControlPermission.READ)

        assert section.includes == {}

    def test_revoking_the_last_permission_leaves_an_empty_entry(self) -> None:
        """The group keeps its (now empty) entry, and holds nothing."""
        section = GroupACL({GROUP_ID: ['READ']})

        section.revoke_access(GROUP_ID, AccessControlPermission.READ)

        assert section.includes == {GROUP_ID: set()}
        assert section.verify_access(GROUP_ID, AccessControlPermission.READ) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 verify_access                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestVerifyAccess:
    """The access decision - fail closed."""

    def test_a_stored_permission_is_recognised(self) -> None:
        """The production path: a list of strings from the database."""
        assert _stored_acl({'2': ['READ']}).verify_access(GROUP_ID, AccessControlPermission.READ) is True

    def test_a_permission_that_is_not_granted_is_denied(self) -> None:
        """Only what is listed is allowed."""
        assert _stored_acl({'2': ['READ']}).verify_access(GROUP_ID, AccessControlPermission.DELETE) is False

    def test_an_unknown_key_is_denied(self) -> None:
        """A group with no entry holds no permission."""
        assert _stored_acl({'2': ['READ']}).verify_access(UNKNOWN_GROUP_ID, AccessControlPermission.READ) is False

    def test_an_acl_without_groups_denies_instead_of_raising(self) -> None:
        """A directly constructed ACL used to raise AttributeError into a 500."""
        assert AccessControlList(activated=True).verify_access(GROUP_ID, AccessControlPermission.READ) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                            AccessControlList itself                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAccessControlList:
    """The list around the sections: parsing, serialisation and section dispatch."""

    def test_from_data_reads_activated_and_groups(self) -> None:
        """Both properties come from the stored document."""
        acl = _stored_acl({'2': ['READ']}, activated=True)

        assert acl.activated is True
        assert acl.groups.includes == {GROUP_ID: ['READ']}

    def test_from_data_defaults_to_deactivated(self) -> None:
        """A document without 'activated' is not access controlled."""
        assert AccessControlList.from_data({}).activated is False

    def test_the_round_trip_reproduces_the_wire_format(self) -> None:
        """What comes out is what the frontend sent and the query builder matches against."""
        stored = {
            AclKey.ACTIVATED.value: True,
            AclKey.GROUPS.value: {AclKey.INCLUDES.value: {'2': ['READ', 'UPDATE']}},
        }

        assert AccessControlList.to_json(AccessControlList.from_data(stored)) == stored

    def test_to_json_of_an_acl_without_groups(self) -> None:
        """A group-less ACL serialises to an empty includes mapping, not to None."""
        assert AccessControlList.to_json(AccessControlList(activated=False)) == {
            AclKey.ACTIVATED.value: False,
            AclKey.GROUPS.value: {AclKey.INCLUDES.value: {}},
        }

    def test_grant_access_defaults_to_the_groups_section(self) -> None:
        """The natural two-argument call works (it used to raise ValueError)."""
        acl = AccessControlList(activated=True)

        acl.grant_access(GROUP_ID, AccessControlPermission.DELETE)

        assert acl.verify_access(GROUP_ID, AccessControlPermission.DELETE) is True

    def test_revoke_access_defaults_to_the_groups_section(self) -> None:
        """Same default on the revoke side."""
        acl = _stored_acl({'2': ['READ']})

        acl.revoke_access(GROUP_ID, AccessControlPermission.READ)

        assert acl.verify_access(GROUP_ID, AccessControlPermission.READ) is False

    def test_the_groups_section_may_be_named_explicitly(self) -> None:
        """Passing the section name behaves like the default."""
        acl = AccessControlList(activated=True)

        acl.grant_access(GROUP_ID, AccessControlPermission.READ, section=AclKey.GROUPS.value)

        assert acl.verify_access(GROUP_ID, AccessControlPermission.READ) is True

    @pytest.mark.parametrize('section', ['users', 'roles', '', None])
    def test_an_unknown_section_raises(self, section) -> None:
        """There is exactly one section; anything else is a programming error."""
        acl = _stored_acl()

        with pytest.raises(ValueError):
            acl.grant_access(GROUP_ID, AccessControlPermission.READ, section=section)

        with pytest.raises(ValueError):
            acl.revoke_access(GROUP_ID, AccessControlPermission.READ, section=section)
