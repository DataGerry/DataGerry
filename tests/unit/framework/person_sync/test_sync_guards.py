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
Unit tests for cmdb.framework.person_sync.sync_guards

Pinned: a linked person is never deleted, a mapped person group only while the group sync is off, an ordinary object
always; the settings are read only for a selection holding a mapped group. A target Type - the default or an
override, whether the sync is on or not - is not deleted, and an update may not deactivate it or make it require a
field the sync cannot fill; a Type that is no target is never judged
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.special_type_model.person_type_constants import PersonField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import PersonSyncProblem, SyncGuardProblem
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings
from cmdb.framework.person_sync.sync_guards import (
    enforce_synced_objects_delete,
    synced_object_delete_refusals,
    guarded_person_type_ids,
    target_type_change_refusal,
    target_type_delete_refusal,
    template_change_refusal,
)
# -------------------------------------------------------------------------------------------------------------------- #

GUARDS_PATH: str = 'cmdb.framework.person_sync.sync_guards'
PERSON_ID: int = 801
GROUP_OBJECT_ID: int = 802
PLAIN_ID: int = 803
USER_ID: int = 9
USER_GROUP_ID: int = 4
DEFAULT_TYPE_ID: int = 51
OVERRIDE_TYPE_ID: int = 52
OTHER_TYPE_ID: int = 53
TEMPLATE_NAME: str = 'badge'
TEMPLATE_FIELD: str = 'badge_number'

PERSON: dict[str, Any] = {'public_id': PERSON_ID, 'system_ref': {'kind': 'user', 'id': USER_ID}}
GROUP: dict[str, Any] = {'public_id': GROUP_OBJECT_ID, 'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID}}
PLAIN: dict[str, Any] = {'public_id': PLAIN_ID}

CONFIGURED: PersonSyncSettings = PersonSyncSettings(
    users=UserSyncSettings(default_type_id=DEFAULT_TYPE_ID, type_overrides={USER_ID: OVERRIDE_TYPE_ID}),
)
# The Types the sync writes persons into when no linked person lives outside its targets
GUARDED: set[int] = {DEFAULT_TYPE_ID, OVERRIDE_TYPE_ID}


def _person_type(public_id: int, active: bool = True, required: tuple[str, ...] = ()) -> CmdbType:
    """A PERSON Type from the blueprint, the named fields required"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, f'person-{public_id}', public_id)
    document['active'] = active

    for type_field in document['fields']:
        if type_field['name'] in required:
            type_field['required'] = True

    return CmdbType.from_data(document)


class TestObjectDelete:
    """What the sync keeps from being deleted."""

    def test_a_linked_person_is_refused_whatever_the_switches(self) -> None:
        """It goes when its user does"""
        assert synced_object_delete_refusals([PERSON], False) == [
            SyncGuardProblem.SYNCED_PERSON_DELETE.value.format(public_id=PERSON_ID, user_id=USER_ID),
        ]

    def test_a_mapped_group_is_refused_while_the_group_sync_is_on(self) -> None:
        """Its members are the sync's"""
        assert synced_object_delete_refusals([GROUP], True) == [
            SyncGuardProblem.MAPPED_GROUP_DELETE.value.format(public_id=GROUP_OBJECT_ID, group_id=USER_GROUP_ID),
        ]

    def test_a_mapped_group_may_go_while_the_group_sync_is_off(self) -> None:
        """Off means unlocked"""
        assert synced_object_delete_refusals([GROUP], False) == []

    def test_an_ordinary_object_is_never_refused(self) -> None:
        """No link, no guard"""
        assert synced_object_delete_refusals([PLAIN], True) == []

    def test_every_kept_target_of_a_selection_is_named(self) -> None:
        """In the selection's order"""
        assert synced_object_delete_refusals([PLAIN, GROUP, PERSON], True) == [
            SyncGuardProblem.MAPPED_GROUP_DELETE.value.format(public_id=GROUP_OBJECT_ID, group_id=USER_GROUP_ID),
            SyncGuardProblem.SYNCED_PERSON_DELETE.value.format(public_id=PERSON_ID, user_id=USER_ID),
        ]

    @pytest.mark.parametrize('selection', [[PLAIN], [PERSON, PLAIN]], ids=['ordinary', 'person'])
    def test_no_mapped_group_reads_no_settings(self, selection: list[dict[str, Any]]) -> None:
        """An ordinary delete costs nothing"""
        with patch(f'{GUARDS_PATH}.read_sync_settings') as read:
            enforce_synced_objects_delete(MagicMock(), selection)

        read.assert_not_called()

    def test_a_mapped_group_reads_the_switch(self) -> None:
        """Refused while the stored group sync is on"""
        settings = PersonSyncSettings(groups=GroupSyncSettings(active=True))

        with patch(f'{GUARDS_PATH}.read_sync_settings', return_value=settings) as read:
            refusal = enforce_synced_objects_delete(MagicMock(), [GROUP])

        read.assert_called_once()
        assert refusal == SyncGuardProblem.MAPPED_GROUP_DELETE.value.format(public_id=GROUP_OBJECT_ID,
                                                                            group_id=USER_GROUP_ID)


class TestTargetTypeDelete:
    """A chosen target is not deleted."""

    @pytest.mark.parametrize('type_id', [DEFAULT_TYPE_ID, OVERRIDE_TYPE_ID], ids=['default', 'override'])
    def test_a_target_is_refused_even_while_the_sync_is_off(self, type_id: int) -> None:
        """Chosen is enough - switching on would write into it"""
        assert target_type_delete_refusal(CONFIGURED, type_id) == SyncGuardProblem.TARGET_TYPE_DELETE.value.format(
            type_id=type_id)

    def test_another_type_may_go(self) -> None:
        """No target, no guard"""
        assert target_type_delete_refusal(CONFIGURED, OTHER_TYPE_ID) is None


class TestTargetTypeChange:
    """A target stays one the sync can write into."""

    def test_a_usable_update_passes(self) -> None:
        """The blueprint's Type"""
        assert target_type_change_refusal(GUARDED, _person_type(DEFAULT_TYPE_ID)) is None

    def test_deactivating_a_target_is_refused(self) -> None:
        """Its objects could no longer be written"""
        assert target_type_change_refusal(GUARDED, _person_type(OVERRIDE_TYPE_ID, active=False)) == (
            SyncGuardProblem.TARGET_TYPE_CHANGE.value.format(
                type_id=OVERRIDE_TYPE_ID,
                problems=PersonSyncProblem.TYPE_INACTIVE.value.format(type_id=OVERRIDE_TYPE_ID)))

    def test_requiring_a_name_again_is_refused(self) -> None:
        """A user may carry no first name"""
        refusal = target_type_change_refusal(GUARDED,
                                             _person_type(DEFAULT_TYPE_ID, required=(PersonField.FIRST_NAME.value,)))

        assert refusal == SyncGuardProblem.TARGET_TYPE_CHANGE.value.format(
            type_id=DEFAULT_TYPE_ID,
            problems=PersonSyncProblem.TYPE_UNFILLABLE_FIELDS.value.format(type_id=DEFAULT_TYPE_ID,
                                                                           names=[PersonField.FIRST_NAME.value]))

    def test_a_type_that_is_no_target_is_never_judged(self) -> None:
        """Deactivate it, require what you like"""
        assert target_type_change_refusal(GUARDED, _person_type(OTHER_TYPE_ID, active=False)) is None

    def test_a_type_holding_a_linked_person_is_judged_like_a_target(self) -> None:
        """A person left in a Type that is no target is still written where it lives"""
        refusal = target_type_change_refusal(GUARDED | {OTHER_TYPE_ID}, _person_type(OTHER_TYPE_ID, active=False))

        assert refusal == SyncGuardProblem.TARGET_TYPE_CHANGE.value.format(
            type_id=OTHER_TYPE_ID, problems=PersonSyncProblem.TYPE_INACTIVE.value.format(type_id=OTHER_TYPE_ID))


def test_the_guarded_types_are_the_targets_and_where_linked_persons_live() -> None:
    """One distinct read of the linked persons' Types"""
    objects = MagicMock()
    objects.get_distinct.return_value = [OTHER_TYPE_ID, DEFAULT_TYPE_ID]

    assert guarded_person_type_ids(CONFIGURED, objects) == GUARDED | {OTHER_TYPE_ID}
    objects.get_distinct.assert_called_once_with('type_id', {'system_ref.kind': 'user'})




class TestTemplateChange:
    """A global template's update is copied into the targets carrying it."""

    @staticmethod
    def _field(**rules: Any) -> dict[str, Any]:
        """The template's text field with the given rules"""
        return {'type': 'text', 'name': TEMPLATE_FIELD, 'label': 'Badge', **rules}

    def test_a_required_field_without_default_is_refused(self) -> None:
        """Naming the target Types and the fields"""
        assert template_change_refusal(TEMPLATE_NAME, [self._field(required=True)], False,
                                       [OVERRIDE_TYPE_ID, DEFAULT_TYPE_ID]) == (
            SyncGuardProblem.TARGET_TEMPLATE_CHANGE.value.format(
                name=TEMPLATE_NAME, type_ids=[DEFAULT_TYPE_ID, OVERRIDE_TYPE_ID], names=[TEMPLATE_FIELD]))

    def test_a_required_field_with_a_default_passes(self) -> None:
        """The create fills it"""
        assert template_change_refusal(TEMPLATE_NAME, [self._field(required=True, value='B-1')], False,
                                       [DEFAULT_TYPE_ID]) is None

    def test_a_multi_data_section_template_passes(self) -> None:
        """Its fields live in rows the sync never writes"""
        assert template_change_refusal(TEMPLATE_NAME, [self._field(required=True)], True, [DEFAULT_TYPE_ID]) is None

    def test_no_target_carrying_it_passes(self) -> None:
        """Every other Type's own business"""
        assert template_change_refusal(TEMPLATE_NAME, [self._field(required=True)], False, []) is None
