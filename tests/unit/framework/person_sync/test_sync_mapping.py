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
Unit tests for cmdb.framework.person_sync.sync_mapping

Pinned: a person's synced values are its user's - the display name always set, first name / last name / email or
empty, nothing else copied; an optional value the target Type's rules refuse is written empty, the display name never;
the person is active exactly while its user is; the fingerprint follows the values and the active state, not their
order; a person group's name is its user group's label; the synced members are the user group's users' persons in id
order; the persons added by hand stay ahead of them. Pure - every test builds its users and groups in memory
"""
from typing import Any

import pytest

from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.person_type_constants import PERSON_EMAIL_PATTERN, PersonField
from cmdb.framework.object_field_value_rules import FieldValueRule, build_field_value_rules
from cmdb.framework.person_sync.person_sync_constants import EMPTY_SYNCED_VALUE, SYNCED_PERSON_FIELDS
from cmdb.framework.person_sync.sync_mapping import (
    SyncedPerson,
    merge_group_members,
    person_group_name,
    persons_of_users,
    sync_fingerprint,
    synced_member_ids,
    synced_person_from_user,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 12
USER_NAME: str = 'alee'
FIRST_NAME: str = 'Ann'
LAST_NAME: str = 'Lee'
EMAIL: str = 'ann.lee@example.org'
BAD_EMAIL: str = 'ann.lee@'
FULL_NAME: str = f'{FIRST_NAME} {LAST_NAME}'
GROUP_ID: int = 5
OTHER_GROUP_ID: int = 6
GROUP_NAME: str = 'service-desk'
GROUP_LABEL: str = 'Service Desk'
HAND_ADDED: int = 900
OTHER_HAND_ADDED: int = 901

# The PERSON blueprint's rules: the text cap on every name, the email pattern
PERSON_RULES: dict[str, FieldValueRule] = build_field_value_rules([
    {'type': 'text', 'name': PersonField.DISPLAY_NAME.value},
    {'type': 'text', 'name': PersonField.FIRST_NAME.value},
    {'type': 'text', 'name': PersonField.LAST_NAME.value},
    {'type': 'text', 'name': PersonField.EMAIL.value, 'regex': PERSON_EMAIL_PATTERN},
])


def _user(**overrides: Any) -> CmdbUser:
    """A user with every name and an email, the given attributes replaced"""
    attributes: dict[str, Any] = {
        'public_id': USER_ID, 'user_name': USER_NAME, 'active': True, 'group_ids': [GROUP_ID],
        'first_name': FIRST_NAME, 'last_name': LAST_NAME, 'email': EMAIL, 'password': 'never-copied',
    }
    attributes.update(overrides)

    return CmdbUser(**attributes)


class TestSyncedPersonFromUser:
    """The values a user gives its person."""

    def test_a_complete_user_gives_every_value(self) -> None:
        """The display name is the full name"""
        person = synced_person_from_user(_user(), PERSON_RULES)

        assert person == SyncedPerson(values={
            PersonField.DISPLAY_NAME.value: FULL_NAME,
            PersonField.FIRST_NAME.value: FIRST_NAME,
            PersonField.LAST_NAME.value: LAST_NAME,
            PersonField.EMAIL.value: EMAIL,
        }, active=True)

    def test_only_the_shared_fields_are_copied(self) -> None:
        """No password, no API level, no phone number - the person's own field"""
        assert tuple(synced_person_from_user(_user(), PERSON_RULES).values) == SYNCED_PERSON_FIELDS

    def test_a_user_without_names_is_shown_by_its_user_name(self) -> None:
        """The display name always has a value; the missing ones are written empty"""
        person = synced_person_from_user(_user(first_name=None, last_name=None, email=None), PERSON_RULES)

        assert person.values == {
            PersonField.DISPLAY_NAME.value: USER_NAME,
            PersonField.FIRST_NAME.value: EMPTY_SYNCED_VALUE,
            PersonField.LAST_NAME.value: EMPTY_SYNCED_VALUE,
            PersonField.EMAIL.value: EMPTY_SYNCED_VALUE,
        }

    def test_a_first_name_alone_is_kept_but_not_the_display_name(self) -> None:
        """'Ann' alone reads as a login - the user model's own display rule"""
        person = synced_person_from_user(_user(last_name=None), PERSON_RULES)

        assert person.values[PersonField.DISPLAY_NAME.value] == USER_NAME
        assert person.values[PersonField.FIRST_NAME.value] == FIRST_NAME

    def test_an_email_the_pattern_refuses_is_written_empty(self) -> None:
        """Rather than failing the person's write"""
        person = synced_person_from_user(_user(email=BAD_EMAIL), PERSON_RULES)

        assert person.values[PersonField.EMAIL.value] == EMPTY_SYNCED_VALUE

    def test_a_target_types_own_pattern_judges_the_other_values_too(self) -> None:
        """A Type may give its names a pattern - a refused name is written empty"""
        rules = build_field_value_rules([{'type': 'text', 'name': PersonField.LAST_NAME.value, 'regex': '[A-Z]+'}])

        person = synced_person_from_user(_user(), rules)

        assert person.values[PersonField.LAST_NAME.value] == EMPTY_SYNCED_VALUE
        assert person.values[PersonField.FIRST_NAME.value] == FIRST_NAME

    def test_the_display_name_is_never_emptied(self) -> None:
        """A required value: a Type refusing it fails that one write, which names the field"""
        rules = build_field_value_rules([{'type': 'text', 'name': PersonField.DISPLAY_NAME.value, 'regex': '[0-9]+'}])

        assert synced_person_from_user(_user(), rules).values[PersonField.DISPLAY_NAME.value] == FULL_NAME

    def test_without_rules_every_value_is_kept(self) -> None:
        """A Type that declares none"""
        assert synced_person_from_user(_user(email=BAD_EMAIL), {}).values[PersonField.EMAIL.value] == BAD_EMAIL

    @pytest.mark.parametrize('active', [True, False])
    def test_the_person_is_active_exactly_while_its_user_is(self, active: bool) -> None:
        """A deactivated user's person is deactivated"""
        assert synced_person_from_user(_user(active=active), PERSON_RULES).active is active


class TestFingerprint:
    """What decides whether a person needs a write."""

    def test_the_same_values_give_the_same_fingerprint(self) -> None:
        """Built twice from the same user"""
        first = synced_person_from_user(_user(), PERSON_RULES)
        second = synced_person_from_user(_user(), PERSON_RULES)

        assert first.fingerprint() == second.fingerprint()

    @pytest.mark.parametrize('change', [{'email': 'ann@example.org'}, {'active': False}, {'last_name': 'Li'}],
                             ids=['email', 'active', 'last-name'])
    def test_a_changed_value_or_state_changes_it(self, change: dict[str, Any]) -> None:
        """Every synced value and the active state count"""
        assert (synced_person_from_user(_user(), PERSON_RULES).fingerprint()
                != synced_person_from_user(_user(**change), PERSON_RULES).fingerprint())

    def test_the_key_order_does_not_count(self) -> None:
        """A dict built in another order is the same payload"""
        assert sync_fingerprint({'a': 1, 'b': [2, 3]}) == sync_fingerprint({'b': [2, 3], 'a': 1})

    def test_a_list_order_does(self) -> None:
        """Members in another order are other members"""
        assert sync_fingerprint({'a': [1, 2]}) != sync_fingerprint({'a': [2, 1]})


class TestPersonGroupName:
    """A mapped person group's name."""

    def test_the_label_is_the_name(self) -> None:
        """What the user group screens show"""
        assert person_group_name(CmdbUserGroup(public_id=GROUP_ID, name=GROUP_NAME, label=GROUP_LABEL)) == GROUP_LABEL

    def test_without_a_label_the_titled_name(self) -> None:
        """The user group model's own default label"""
        assert person_group_name(CmdbUserGroup(public_id=GROUP_ID, name=GROUP_NAME)) == GROUP_NAME.title()


class TestSyncedMembers:
    """A mapped person group's synced members."""

    def test_the_persons_of_the_groups_users_in_id_order(self) -> None:
        """A user in several groups is a member of each mapped one"""
        group_ids_by_user = {1: [GROUP_ID], 2: [OTHER_GROUP_ID], 3: [OTHER_GROUP_ID, GROUP_ID]}
        person_id_by_user = {1: 103, 2: 102, 3: 101}

        assert synced_member_ids(GROUP_ID, group_ids_by_user, person_id_by_user) == [101, 103]

    def test_a_user_without_a_person_is_left_out(self) -> None:
        """The pass that creates the person adds it"""
        assert synced_member_ids(GROUP_ID, {1: [GROUP_ID], 2: [GROUP_ID]}, {2: 102}) == [102]


class TestMergeGroupMembers:
    """The hand-added persons kept, the synced ones replaced."""

    def test_the_hand_added_stay_ahead_in_their_order(self) -> None:
        """Then the synced members"""
        assert merge_group_members([OTHER_HAND_ADDED, 101, HAND_ADDED], {101, 102}, [101, 102]) == [
            OTHER_HAND_ADDED, HAND_ADDED, 101, 102,
        ]

    def test_a_synced_person_the_user_group_no_longer_gives_leaves(self) -> None:
        """Its user left the user group"""
        assert merge_group_members([101, 102, HAND_ADDED], {101, 102}, [102]) == [HAND_ADDED, 102]

    def test_each_member_once(self) -> None:
        """A repeated stored member or synced member is stored once"""
        assert merge_group_members([HAND_ADDED, HAND_ADDED], {101}, [101, 101]) == [HAND_ADDED, 101]


def test_the_persons_of_users_ascending_without_the_personless() -> None:
    """A user without a person yet is left out"""
    assert persons_of_users([3, 1, 2], {1: 30, 3: 10}) == [10, 30]
