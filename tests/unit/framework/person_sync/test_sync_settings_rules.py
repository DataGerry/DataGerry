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
Unit tests for cmdb.framework.person_sync.sync_settings_rules

Pinned per rule: a target Type exists, carries PERSON, is active and requires only what the sync always fills (the
display name) or what has a usable default - a multi-data section's field never counts; the user sync is switched on
only with a default Type; an override names an existing user; the group sync needs the user sync and a PERSON_GROUP
Type. ``find_sync_settings_problems`` reads each input once, and only when it is needed. The Types are built from the
current PERSON blueprint; no Mongo, no Flask
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.models.special_type_model.person_type_constants import PersonField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import (
    PERSON_GROUP_FILLED_FIELDS,
    GroupMappingProblem,
    PersonSyncProblem,
)
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings
from cmdb.framework.person_sync.sync_settings_rules import (
    find_sync_settings_problems,
    group_sync_problems,
    target_type_problems,
    unfillable_required_fields,
    usable_person_group_type,
    usable_target_type,
    user_sync_problems,
)
from cmdb.errors.person_sync import PersonSyncTargetError
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE_ID: int = 31
OTHER_PERSON_TYPE_ID: int = 32
GROUP_TYPE_ID: int = 33
MISSING_TYPE_ID: int = 39
USER_ID: int = 4
MISSING_USER_ID: int = 8
OWN_FIELD: str = 'badge_number'
ROW_FIELD: str = 'previous_badge'
ROWS_SECTION: str = 'badge_history'
OWN_DEFAULT: str = 'B-000'


def _person_type(public_id: int = PERSON_TYPE_ID, active: bool = True,
                 extra_fields: list[dict[str, Any]] | None = None,
                 extra_sections: list[dict[str, Any]] | None = None,
                 required: tuple[str, ...] = ()) -> CmdbType:
    """A Type built from the PERSON blueprint, with its own fields and sections and the named fields required"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, f'person-{public_id}', public_id)
    document['active'] = active
    document['fields'].extend(extra_fields or [])
    document['render_meta']['sections'].extend(extra_sections or [])

    for type_field in document['fields']:
        if type_field['name'] in required:
            type_field['required'] = True

    return CmdbType.from_data(document)


def _group_type() -> CmdbType:
    """A Type built from the PERSON_GROUP blueprint"""
    return CmdbType.from_data(build_default_person_type(SpecialType.PERSON_GROUP, 'person-group', GROUP_TYPE_ID))


def _own_field(required: bool, default: Any = None) -> dict[str, Any]:
    """The Type's own text field"""
    own: dict[str, Any] = {'type': 'text', 'name': OWN_FIELD, 'label': 'Badge', 'required': required}

    if default is not None:
        own['value'] = default

    return own


def _row_type() -> CmdbType:
    """A PERSON Type whose own required field lives in a multi-data section"""
    return _person_type(
        extra_fields=[{'type': 'text', 'name': ROW_FIELD, 'label': 'Previous badge', 'required': True}],
        extra_sections=[{'type': 'multi-data-section', 'name': ROWS_SECTION, 'label': 'History',
                         'fields': [ROW_FIELD]}],
    )


class TestUnfillableRequiredFields:
    """What the sync cannot fill."""

    def test_the_blueprint_requires_only_what_the_sync_fills(self) -> None:
        """The display name is filled for every user"""
        assert unfillable_required_fields(_person_type()) == []

    @pytest.mark.parametrize('name', [PersonField.FIRST_NAME.value, PersonField.LAST_NAME.value,
                                      PersonField.EMAIL.value, PersonField.PHONE_NUMBER.value])
    def test_a_name_email_or_phone_flagged_again_is_named(self, name: str) -> None:
        """A user may carry none of them"""
        assert unfillable_required_fields(_person_type(required=(name,))) == [name]

    def test_a_required_own_field_without_a_default_is_named(self) -> None:
        """The sync knows nothing of the Type's own fields"""
        assert unfillable_required_fields(_person_type(extra_fields=[_own_field(True)])) == [OWN_FIELD]

    def test_a_required_own_field_with_a_default_is_fine(self) -> None:
        """The create fills it from the default"""
        assert unfillable_required_fields(_person_type(extra_fields=[_own_field(True, OWN_DEFAULT)])) == []

    def test_an_optional_own_field_is_fine(self) -> None:
        """Only required fields count"""
        assert unfillable_required_fields(_person_type(extra_fields=[_own_field(False)])) == []

    def test_a_required_field_of_a_multi_data_section_is_fine(self) -> None:
        """The sync writes no rows, so a row's required field is never missing"""
        assert unfillable_required_fields(_row_type()) == []

    def test_several_are_named_in_order(self) -> None:
        """Sorted, so the message is stable"""
        type_instance = _person_type(extra_fields=[_own_field(True)],
                                     required=(PersonField.LAST_NAME.value, PersonField.EMAIL.value))

        assert unfillable_required_fields(type_instance) == [
            OWN_FIELD, PersonField.EMAIL.value, PersonField.LAST_NAME.value,
        ]


class TestTargetTypeProblems:
    """One target Type."""

    def test_a_usable_person_type_has_no_problem(self) -> None:
        """Active, PERSON, nothing unfillable"""
        assert target_type_problems(PERSON_TYPE_ID, _person_type()) == []

    def test_a_missing_type(self) -> None:
        """The only problem named for it"""
        assert target_type_problems(MISSING_TYPE_ID, None) == [
            PersonSyncProblem.TYPE_MISSING.value.format(type_id=MISSING_TYPE_ID),
        ]

    def test_a_type_without_the_person_marker(self) -> None:
        """A person group Type is no person Type"""
        assert target_type_problems(GROUP_TYPE_ID, _group_type()) == [
            PersonSyncProblem.TYPE_NOT_PERSON.value.format(type_id=GROUP_TYPE_ID),
        ]

    def test_a_deactivated_and_unfillable_type_names_both(self) -> None:
        """Every problem of the Type at once"""
        type_instance = _person_type(active=False, required=(PersonField.FIRST_NAME.value,))

        assert target_type_problems(PERSON_TYPE_ID, type_instance) == [
            PersonSyncProblem.TYPE_INACTIVE.value.format(type_id=PERSON_TYPE_ID),
            PersonSyncProblem.TYPE_UNFILLABLE_FIELDS.value.format(type_id=PERSON_TYPE_ID,
                                                                  names=[PersonField.FIRST_NAME.value]),
        ]


class TestUserSyncProblems:
    """The user sync's settings."""

    def test_switched_on_without_a_default_type(self) -> None:
        """A sync without a target writes nowhere"""
        assert user_sync_problems(UserSyncSettings(active=True), {}, set()) == [
            PersonSyncProblem.NO_DEFAULT_TYPE.value,
        ]

    def test_switched_off_without_a_default_type_is_fine(self) -> None:
        """Nothing chosen yet, nothing running"""
        assert user_sync_problems(UserSyncSettings(), {}, set()) == []

    def test_every_target_is_judged_even_while_off(self) -> None:
        """An override chosen while off is used the moment the sync is switched on"""
        users = UserSyncSettings(default_type_id=PERSON_TYPE_ID, type_overrides={USER_ID: MISSING_TYPE_ID})

        assert user_sync_problems(users, {PERSON_TYPE_ID: _person_type()}, {USER_ID}) == [
            PersonSyncProblem.TYPE_MISSING.value.format(type_id=MISSING_TYPE_ID),
        ]

    def test_an_override_names_an_existing_user(self) -> None:
        """A missing user is named"""
        users = UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID,
                                 type_overrides={MISSING_USER_ID: PERSON_TYPE_ID})

        assert user_sync_problems(users, {PERSON_TYPE_ID: _person_type()}, set()) == [
            PersonSyncProblem.OVERRIDE_USER_MISSING.value.format(user_id=MISSING_USER_ID),
        ]

    def test_a_usable_configuration_has_no_problem(self) -> None:
        """Default and override usable, the user exists"""
        users = UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID,
                                 type_overrides={USER_ID: OTHER_PERSON_TYPE_ID})
        types = {PERSON_TYPE_ID: _person_type(), OTHER_PERSON_TYPE_ID: _person_type(OTHER_PERSON_TYPE_ID)}

        assert user_sync_problems(users, types, {USER_ID}) == []


class TestGroupSyncProblems:
    """The user group sync's settings."""

    def test_off_without_a_default_has_no_problem(self) -> None:
        """Whatever else is missing"""
        assert group_sync_problems(UserSyncSettings(), GroupSyncSettings(), {}) == []

    def test_on_without_the_user_sync_and_a_default(self) -> None:
        """Both named"""
        assert group_sync_problems(UserSyncSettings(), GroupSyncSettings(active=True), {}) == [
            PersonSyncProblem.GROUPS_WITHOUT_USERS.value,
            PersonSyncProblem.NO_DEFAULT_GROUP_TYPE.value,
        ]

    def test_on_with_both_is_fine(self) -> None:
        """The user sync on, a usable default"""
        assert group_sync_problems(UserSyncSettings(active=True),
                                   GroupSyncSettings(active=True, default_type_id=GROUP_TYPE_ID),
                                   {GROUP_TYPE_ID: _group_type()}) == []

    @pytest.mark.parametrize('active', [True, False], ids=['on', 'off'])
    def test_a_chosen_default_is_judged_on_or_off(self, active: bool) -> None:
        """A PERSON Type as the default - refused either way"""
        groups = GroupSyncSettings(active=active, default_type_id=PERSON_TYPE_ID)

        assert group_sync_problems(UserSyncSettings(active=True), groups, {PERSON_TYPE_ID: _person_type()}) == [
            GroupMappingProblem.TYPE_NOT_PERSON_GROUP.value.format(type_id=PERSON_TYPE_ID)]

    def test_a_missing_default(self) -> None:
        """Named as missing"""
        groups = GroupSyncSettings(default_type_id=MISSING_TYPE_ID)

        assert group_sync_problems(UserSyncSettings(), groups, {}) == [
            PersonSyncProblem.TYPE_MISSING.value.format(type_id=MISSING_TYPE_ID)]


class TestUsablePersonGroupType:
    """usable_person_group_type - what the engine and the pass create person groups in"""

    def test_a_usable_default_is_answered(self) -> None:
        """The Type itself"""
        group_type = _group_type()

        assert usable_person_group_type(GROUP_TYPE_ID, group_type) is group_type

    @pytest.mark.parametrize('type_id, type_instance, expected', [
        (None, None, PersonSyncProblem.NO_DEFAULT_GROUP_TYPE.value),
        (MISSING_TYPE_ID, None, PersonSyncProblem.TYPE_MISSING.value.format(type_id=MISSING_TYPE_ID)),
    ], ids=['none-chosen', 'missing'])
    def test_an_unusable_default_is_refused(self, type_id: Any, type_instance: Any, expected: str) -> None:
        """PersonSyncTargetError naming why"""
        with pytest.raises(PersonSyncTargetError) as raised:
            usable_person_group_type(type_id, type_instance)

        assert str(raised.value) == expected


class TestFindSyncSettingsProblems:
    """The reads, and the problems of both syncs in one answer."""

    @staticmethod
    def _managers(types: dict[int, CmdbType], users: set[int]) -> tuple[MagicMock, MagicMock]:
        """Managers answering the given Types and users"""
        types_manager, users_manager = MagicMock(), MagicMock()
        types_manager.get_types_lookup.return_value = types
        users_manager.get_user_lookup.return_value = {user_id: MagicMock() for user_id in users}

        return types_manager, users_manager

    def test_each_input_is_read_once(self) -> None:
        """The targets and the group default in one read, in id order; the override users"""
        settings = PersonSyncSettings(
            users=UserSyncSettings(active=True, default_type_id=OTHER_PERSON_TYPE_ID,
                                   type_overrides={USER_ID: PERSON_TYPE_ID}),
            groups=GroupSyncSettings(active=True, default_type_id=GROUP_TYPE_ID),
        )
        types = {PERSON_TYPE_ID: _person_type(), OTHER_PERSON_TYPE_ID: _person_type(OTHER_PERSON_TYPE_ID),
                 GROUP_TYPE_ID: _group_type()}
        types_manager, users_manager = self._managers(types, {USER_ID})

        assert find_sync_settings_problems(settings, types_manager, users_manager) == []
        types_manager.get_types_lookup.assert_called_once_with([PERSON_TYPE_ID, OTHER_PERSON_TYPE_ID, GROUP_TYPE_ID])
        users_manager.get_user_lookup.assert_called_once_with([USER_ID])

    def test_what_is_not_needed_is_not_read(self) -> None:
        """No override, no user read; no group default, only the user target read"""
        settings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID))
        types_manager, users_manager = self._managers({PERSON_TYPE_ID: _person_type()}, set())

        assert find_sync_settings_problems(settings, types_manager, users_manager) == []
        users_manager.get_user_lookup.assert_not_called()
        types_manager.get_types_lookup.assert_called_once_with([PERSON_TYPE_ID])

    def test_both_syncs_problems_in_one_answer(self) -> None:
        """The user sync's first"""
        settings = PersonSyncSettings(users=UserSyncSettings(default_type_id=MISSING_TYPE_ID),
                                      groups=GroupSyncSettings(active=True))
        types_manager, users_manager = self._managers({}, set())

        assert find_sync_settings_problems(settings, types_manager, users_manager) == [
            PersonSyncProblem.TYPE_MISSING.value.format(type_id=MISSING_TYPE_ID),
            PersonSyncProblem.GROUPS_WITHOUT_USERS.value,
            PersonSyncProblem.NO_DEFAULT_GROUP_TYPE.value,
        ]

    def test_a_failed_read_propagates(self) -> None:
        """The database's failure is not the settings' - no problem list hides it"""
        settings = PersonSyncSettings(users=UserSyncSettings(default_type_id=PERSON_TYPE_ID))
        types_manager, users_manager = self._managers({}, set())
        failure = RuntimeError('types gone')
        types_manager.get_types_lookup.side_effect = failure

        with pytest.raises(RuntimeError) as raised:
            find_sync_settings_problems(settings, types_manager, users_manager)

        assert raised.value is failure



class TestFilledFields:
    """The fields the sync fills are the caller's choice."""

    def test_a_person_group_type_requires_nothing_the_group_sync_cannot_fill(self) -> None:
        """Name and members are filled for every mapped person group"""
        assert unfillable_required_fields(_group_type(), PERSON_GROUP_FILLED_FIELDS) == []

    def test_the_display_name_counts_only_for_a_person(self) -> None:
        """Filled for a person, not when only a group's fields are filled"""
        assert unfillable_required_fields(_person_type(), PERSON_GROUP_FILLED_FIELDS) == [
            PersonField.DISPLAY_NAME.value,
        ]



class TestUsableTargetType:
    """usable_target_type"""

    def test_a_usable_type_is_answered(self) -> None:
        """As given"""
        person_type: CmdbType = _person_type()

        assert usable_target_type(PERSON_TYPE_ID, person_type) is person_type

    @pytest.mark.parametrize('type_id, found, expected', [
        (None, None, 'does not exist'),
        (MISSING_TYPE_ID, None, 'does not exist'),
        (PERSON_TYPE_ID, 'inactive', 'deactivated'),
    ], ids=['unchosen', 'gone', 'unusable'])
    def test_an_unusable_type_is_refused(self, type_id: Any, found: Any, expected: str) -> None:
        """The sync's error, naming why"""
        type_instance: CmdbType | None = _person_type(active=False) if found else None

        with pytest.raises(PersonSyncTargetError) as caught:
            usable_target_type(type_id, type_instance)

        assert expected in str(caught.value)
