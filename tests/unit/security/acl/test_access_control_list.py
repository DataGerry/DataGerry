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

Pins the four rules: granting to a key the section does not know yet works at all (it
raised TypeError from instantiating a typing alias), grant and verify agree (grant stored the enum
member while verify compared its value, so a freshly granted permission read back as denied), an ACL
without a groups section denies instead of raising, and revoking is idempotent.
"""
import json
from typing import Any

import pytest

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

    def test_reassigning_includes_replaces_the_mapping(self) -> None:
        """The setter is the one entry point - a later assignment goes through it as well."""
        section = _PlainSection({GROUP_ID: ['READ']})

        section.includes = {OTHER_GROUP_ID: ['DELETE']}

        assert section.includes == {OTHER_GROUP_ID: ['DELETE']}


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

    def test_from_data_with_null_includes_is_empty(self) -> None:
        """The type write schema lets includes be null; it reads as no group."""
        assert GroupACL.from_data({AclKey.INCLUDES.value: None}).includes == {}

    def test_constructed_without_includes_is_empty(self) -> None:
        """The same default as the base section."""
        assert GroupACL().includes == {}

    def test_mixed_string_and_int_keys_all_become_int(self) -> None:
        """A stored key and an in-memory key land on the same int."""
        section = GroupACL({'2': ['READ'], OTHER_GROUP_ID: ['DELETE']})

        assert section.includes == {GROUP_ID: ['READ'], OTHER_GROUP_ID: ['DELETE']}

    def test_a_later_assignment_converts_the_keys_too(self) -> None:
        """The key conversion sits behind the setter, not only behind the constructor."""
        section = GroupACL({})

        section.includes = {'3': ['UPDATE']}

        assert section.includes == {OTHER_GROUP_ID: ['UPDATE']}

    def test_the_permission_containers_are_kept_as_given(self) -> None:
        """Only the keys change; a stored list stays a list until a mutator touches it."""
        section = GroupACL({'2': ['UPDATE', 'READ']})

        assert section.includes[GROUP_ID] == ['UPDATE', 'READ']

    def test_a_key_that_is_no_whole_number_raises(self) -> None:
        """The write schema only admits digit keys; anything else is a programming error here."""
        with pytest.raises(ValueError):
            GroupACL({'abc': ['READ']})

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
        """The first grant for a group must not raise TypeError."""
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
        """It must not raise ValueError."""
        section = GroupACL({GROUP_ID: ['READ']})

        section.revoke_access(GROUP_ID, AccessControlPermission.DELETE)

        assert section.includes == {GROUP_ID: {'READ'}}

    def test_revoking_from_an_unknown_key_is_a_noop(self) -> None:
        """It must not raise KeyError."""
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
        """A directly constructed ACL must not raise AttributeError into a 500."""
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
        """The natural two-argument call works rather than raising ValueError."""
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


# -------------------------------------------------------------------------------------------------------------------- #
#                                         default_json / normalize_stored                                              #
# -------------------------------------------------------------------------------------------------------------------- #
COMPLETE_DEFAULT: dict[str, Any] = {
    AclKey.ACTIVATED.value: False,
    AclKey.GROUPS.value: {AclKey.INCLUDES.value: {}},
}
GRANTED_INCLUDES: dict[str, list[str]] = {'2': ['READ', 'UPDATE']}


class TestDefaultJson:
    """The one spelling of the default block."""

    def test_is_switched_off_and_grants_no_group(self) -> None:
        """The complete block, nothing granted"""
        assert AccessControlList.default_json() == COMPLETE_DEFAULT

    def test_is_a_new_dict_on_every_call(self) -> None:
        """A caller may modify its copy without touching the next one's"""
        first = AccessControlList.default_json()
        first[AclKey.GROUPS.value][AclKey.INCLUDES.value]['1'] = ['READ']

        assert AccessControlList.default_json() == COMPLETE_DEFAULT

    def test_reads_back_as_the_model_default(self) -> None:
        """The same block the model writes for an ACL nobody configured"""
        assert AccessControlList.default_json() == AccessControlList.to_json(AccessControlList.from_data({}))


class TestNormalizeStored:
    """The complete block a stored value reads as."""

    @pytest.mark.parametrize('stored', [None, 'on', 7, ['READ']], ids=['null', 'string', 'number', 'list'])
    def test_a_value_that_is_no_document_is_the_default(self, stored: Any) -> None:
        """Nothing to read: the default"""
        assert AccessControlList.normalize_stored(stored) == COMPLETE_DEFAULT

    @pytest.mark.parametrize('stored', [
        {},
        {AclKey.ACTIVATED.value: False},
        {AclKey.ACTIVATED.value: None},
        {AclKey.ACTIVATED.value: False, AclKey.GROUPS.value: None},
        {AclKey.ACTIVATED.value: False, AclKey.GROUPS.value: {}},
        {AclKey.ACTIVATED.value: False, AclKey.GROUPS.value: {AclKey.INCLUDES.value: None}},
    ], ids=['empty', 'no-groups', 'null-activated', 'null-groups', 'no-includes', 'null-includes'])
    def test_every_incomplete_switched_off_shape_is_the_default(self, stored: dict[str, Any]) -> None:
        """The shapes older types carry: all read as off with no group, so all become the default block"""
        assert AccessControlList.normalize_stored(stored) == COMPLETE_DEFAULT

    def test_groups_without_activated_keep_their_groups_and_read_off(self) -> None:
        """A hand-built ACL with groups but no switch: the groups stay, the switch is the False it reads as"""
        stored = {AclKey.GROUPS.value: {AclKey.INCLUDES.value: GRANTED_INCLUDES}}

        assert AccessControlList.normalize_stored(stored) == {
            AclKey.ACTIVATED.value: False,
            AclKey.GROUPS.value: {AclKey.INCLUDES.value: GRANTED_INCLUDES},
        }

    def test_a_complete_activated_block_is_unchanged(self) -> None:
        """Nothing to repair"""
        stored = {AclKey.ACTIVATED.value: True, AclKey.GROUPS.value: {AclKey.INCLUDES.value: GRANTED_INCLUDES}}

        assert AccessControlList.normalize_stored(stored) == stored

    @pytest.mark.parametrize(('stored', 'expected'), [('yes', True), (1, True), (0, False), ('', False)])
    def test_a_non_boolean_switch_becomes_the_boolean_it_reads_as(self, stored: Any, expected: bool) -> None:
        """The single read's truthiness - the same reading updater_20261001 wrote"""
        normalized = AccessControlList.normalize_stored({AclKey.ACTIVATED.value: stored})

        assert normalized[AclKey.ACTIVATED.value] is expected

    @pytest.mark.parametrize('stored', [
        {AclKey.ACTIVATED.value: False},
        {AclKey.GROUPS.value: {AclKey.INCLUDES.value: GRANTED_INCLUDES}},
        {AclKey.ACTIVATED.value: True, AclKey.GROUPS.value: {AclKey.INCLUDES.value: GRANTED_INCLUDES}},
        {AclKey.ACTIVATED.value: True, AclKey.GROUPS.value: None},
    ], ids=['off-no-groups', 'groups-no-switch', 'on-with-groups', 'on-null-groups'])
    def test_no_access_decision_changes(self, stored: dict[str, Any]) -> None:
        """For every group and permission the normalized block grants exactly what the stored one did"""
        before = AccessControlList.from_data(stored)
        after = AccessControlList.from_data(AccessControlList.normalize_stored(stored))

        for group_id in [GROUP_ID, OTHER_GROUP_ID, UNKNOWN_GROUP_ID]:
            for permission in AccessControlPermission:
                granted_before = not before.activated or before.verify_access(group_id, permission)
                granted_after = not after.activated or after.verify_access(group_id, permission)
                assert granted_before == granted_after


# -------------------------------------------------------------------------------------------------------------------- #
#                                            stored -> memory -> stored                                                #
# -------------------------------------------------------------------------------------------------------------------- #
STORED_INCLUDES: dict[str, list[str]] = {'2': ['UPDATE', 'READ'], '3': ['DELETE']}


class TestStoredRoundTrip:
    """
    The whole contract of a section, as one chain

    Read from the stored form (string keys, lists), changed in memory (int keys, sets), written back (string
    keys, sorted lists). Each case changes a different key or permission, so a mix-up between keys or between
    grant and revoke ends in a different stored block.
    """

    def test_the_keys_are_ints_in_memory(self) -> None:
        """What a CmdbUser's group_id is compared against."""
        acl = _stored_acl(STORED_INCLUDES)

        assert sorted(acl.groups.includes) == [GROUP_ID, OTHER_GROUP_ID]

    def test_an_untouched_section_is_written_back_sorted(self) -> None:
        """Nothing granted or revoked: the same permissions, each list sorted."""
        acl = _stored_acl(STORED_INCLUDES)

        assert GroupACL.to_json(acl.groups) == {AclKey.INCLUDES.value: {'2': ['READ', 'UPDATE'], '3': ['DELETE']}}

    @pytest.mark.parametrize(('changes', 'expected'), [
        pytest.param(
            [('grant', GROUP_ID, AccessControlPermission.CREATE)],
            {'2': ['CREATE', 'READ', 'UPDATE'], '3': ['DELETE']},
            id='grant-to-a-stored-key',
        ),
        pytest.param(
            [('grant', UNKNOWN_GROUP_ID, AccessControlPermission.READ)],
            {'2': ['READ', 'UPDATE'], '3': ['DELETE'], '99': ['READ']},
            id='grant-to-a-new-key',
        ),
        pytest.param(
            [('revoke', GROUP_ID, AccessControlPermission.UPDATE)],
            {'2': ['READ'], '3': ['DELETE']},
            id='revoke-from-one-key',
        ),
        pytest.param(
            [('revoke', OTHER_GROUP_ID, AccessControlPermission.DELETE)],
            {'2': ['READ', 'UPDATE'], '3': []},
            id='revoke-the-last-permission',
        ),
        pytest.param(
            [('grant', OTHER_GROUP_ID, AccessControlPermission.READ),
             ('revoke', GROUP_ID, AccessControlPermission.READ)],
            {'2': ['UPDATE'], '3': ['DELETE', 'READ']},
            id='grant-one-key-revoke-another',
        ),
    ])
    def test_a_change_is_written_back_in_the_stored_form(
        self, changes: list[tuple[str, int, AccessControlPermission]], expected: dict[str, list[str]],
    ) -> None:
        """String keys, sorted lists of string values - whatever the in-memory containers became."""
        acl = _stored_acl(STORED_INCLUDES)

        for action, group_id, permission in changes:
            if action == 'grant':
                acl.grant_access(group_id, permission)
            else:
                acl.revoke_access(group_id, permission)

        assert GroupACL.to_json(acl.groups) == {AclKey.INCLUDES.value: expected}

    def test_a_written_back_section_reads_as_the_same_decisions(self) -> None:
        """Stored again and read again, every group holds exactly what it held in memory."""
        acl = _stored_acl(STORED_INCLUDES)
        acl.grant_access(UNKNOWN_GROUP_ID, AccessControlPermission.CREATE)
        acl.revoke_access(GROUP_ID, AccessControlPermission.READ)

        reread = AccessControlList.from_data(AccessControlList.to_json(acl))

        for group_id in [GROUP_ID, OTHER_GROUP_ID, UNKNOWN_GROUP_ID]:
            for permission in AccessControlPermission:
                assert reread.verify_access(group_id, permission) == acl.verify_access(group_id, permission)
