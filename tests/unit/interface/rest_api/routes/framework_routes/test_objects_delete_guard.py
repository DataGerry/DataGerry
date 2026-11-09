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
Unit tests for cmdb_objects.objects_delete_guard - what may not be deleted, decided before anything is deleted

The IPAM licence and invariants per target, the Cable CI guard once per selection, the single delete as the batched
guard's one-target form - and every check handed the target's resolved type, so none of them reads it again
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_delete_guard import (
    guard_object_delete,
    guard_object_delete_license,
    guard_objects_delete,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

GUARD_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_delete_guard'
SUBNET_TYPE_ID: int = 31
VLAN_TYPE_ID: int = 32
# What the selection check answers when something outside the selection still references an IPAM target
SELECTION_TYPE_IDS: dict[SpecialType, int | None] = {SpecialType.SUBNET: SUBNET_TYPE_ID, SpecialType.VLAN: VLAN_TYPE_ID}
TYPE_ID: int = 7
OTHER_TYPE_ID: int = 8


# -------------------------------------------------------------------------------------------------------------------- #
#                                          guard_object_delete_license                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardObjectDeleteLicense:
    """guard_object_delete_license delegates to the IPAM license guard only for special-type targets."""

    def test_aborts_when_delete_requires_license(self) -> None:
        """Deleting a special-type object is handed to the license guard."""
        request_user = MagicMock()

        with patch(f'{GUARD_PATH}.object_delete_requires_ipam_license', return_value=True), \
             patch(f'{GUARD_PATH}.abort_if_feature_locked') as guard:
            guard_object_delete_license(MagicMock(), request_user, {})

        guard.assert_called_once_with(LicenseFeature.IPAM, request_user)

    def test_noop_when_delete_not_gated(self) -> None:
        """Deleting an ordinary object never consults the license guard."""
        with patch(f'{GUARD_PATH}.object_delete_requires_ipam_license', return_value=False), \
             patch(f'{GUARD_PATH}.abort_if_feature_locked') as guard:
            guard_object_delete_license(MagicMock(), MagicMock(), {})

        guard.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               guard_object_delete                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardObjectDelete:
    """guard_object_delete is the one-target form of the shared delete guard."""

    def test_passes_when_no_license_gate_and_no_invariant_errors(self) -> None:
        """A non-gated object with no dangling references is a no-op (no abort)."""
        with patch(f'{GUARD_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete'), \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[]) as delete_guards:
            guard_object_delete(MagicMock(), MagicMock(), MagicMock(), {'public_id': 1})

        license_guard.assert_called_once()
        delete_guards.assert_called_once()

    def test_aborts_400_on_invariant_violation(self) -> None:
        """A non-empty delete-guard error list aborts with 400."""
        with patch(f'{GUARD_PATH}.guard_object_delete_license'), \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete'), \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[{'error': 'still referenced'}]), \
             patch(f'{GUARD_PATH}.format_errors_for_abort', return_value='still referenced'):
            with pytest.raises(HTTPException) as exc_info:
                guard_object_delete(MagicMock(), MagicMock(), MagicMock(), {'public_id': 1})

        assert exc_info.value.code == 400

    def test_delegates_to_the_batched_guard_with_one_target(self) -> None:
        """The rules live in the batched function, so the two delete routes cannot drift apart."""
        objects_manager, types_manager, request_user = MagicMock(), MagicMock(), MagicMock()
        target = {'public_id': 1}

        with patch(f'{GUARD_PATH}.guard_objects_delete') as batched:
            guard_object_delete(objects_manager, types_manager, request_user, target)

        batched.assert_called_once_with(objects_manager, types_manager, request_user, [target], {})

    def test_the_cable_guard_runs_for_the_single_delete_too(self) -> None:
        """A Cable CI is refused whichever route deletes it."""
        types_manager, request_user = MagicMock(), MagicMock()
        target = {'public_id': 1}

        with patch(f'{GUARD_PATH}.guard_object_delete_license'), \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[]), \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete') as cable_guard:
            guard_object_delete(MagicMock(), types_manager, request_user, target)

        cable_guard.assert_called_once_with(request_user, types_manager, [target])


# -------------------------------------------------------------------------------------------------------------------- #
#                                              guard_objects_delete                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardObjectsDelete:
    """guard_objects_delete evaluates the delete rules for a whole selection, before anything is deleted."""

    TARGETS: list[dict[str, Any]] = [{'public_id': 1}, {'public_id': 2}, {'public_id': 3}]

    def test_the_ipam_rules_are_evaluated_for_every_target(self) -> None:
        """A bulk delete is refused as a whole, so every target has to be asked up front."""
        with patch(f'{GUARD_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete'), \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[]) as delete_guards:
            guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), self.TARGETS)

        assert license_guard.call_count == len(self.TARGETS)
        assert delete_guards.call_count == len(self.TARGETS)

    def test_the_cable_rule_is_evaluated_once_for_the_selection(self) -> None:
        """One batched read for all targets is what keeps the guard affordable on a bulk delete."""
        types_manager, request_user = MagicMock(), MagicMock()

        with patch(f'{GUARD_PATH}.guard_object_delete_license'), \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[]), \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete') as cable_guard:
            guard_objects_delete(MagicMock(), types_manager, request_user, self.TARGETS)

        cable_guard.assert_called_once_with(request_user, types_manager, self.TARGETS)

    def test_an_ipam_violation_refuses_before_the_cable_read(self) -> None:
        """The first violation aborts; nothing after it needs to be read."""
        with patch(f'{GUARD_PATH}.guard_object_delete_license'), \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[{'error': 'still referenced'}]), \
             patch(f'{GUARD_PATH}.format_errors_for_abort', return_value='still referenced'), \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete') as cable_guard:
            with pytest.raises(HTTPException) as exc_info:
                guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), self.TARGETS)

        assert exc_info.value.code == 400
        cable_guard.assert_not_called()

    def test_a_selection_nothing_references_skips_the_per_target_check(self) -> None:
        """The batched check answering None means no target is blocked - nothing named, nothing read per target."""
        objects_manager, types_manager = MagicMock(), MagicMock()
        held_types: dict[int, Any] = {TYPE_ID: MagicMock()}

        with patch(f'{GUARD_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=None) as selection_check, \
             patch(f'{GUARD_PATH}.enforce_delete_guards') as delete_guards, \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete'):
            guard_objects_delete(objects_manager, types_manager, MagicMock(), self.TARGETS, held_types)

        selection_check.assert_called_once_with(objects_manager, types_manager, self.TARGETS, held_types)
        assert license_guard.call_count == len(self.TARGETS), 'the licence is still asked per target'
        delete_guards.assert_not_called()

    def test_the_per_target_check_leaves_the_selection_out_and_reuses_the_type_ids(self) -> None:
        """Objects deleted together do not block each other; the type ids are not read again."""
        with patch(f'{GUARD_PATH}.guard_object_delete_license'), \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[]) as delete_guards, \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete'):
            guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), self.TARGETS)

        assert all({key: call.kwargs[key] for key in ('exclude_ids', 'ipam_type_ids')}
                   == {'exclude_ids': frozenset({1, 2, 3}), 'ipam_type_ids': SELECTION_TYPE_IDS}
                   for call in delete_guards.call_args_list)
        # One lazy read of the caller's hidden Types serves every target of the selection
        assert len({id(call.kwargs['hidden_types']) for call in delete_guards.call_args_list}) == 1

    def test_an_empty_selection_is_a_no_op(self) -> None:
        """Nothing to delete has nothing to refuse."""
        with patch(f'{GUARD_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{GUARD_PATH}.enforce_delete_guards') as delete_guards, \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete') as cable_guard:
            guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), [])

        license_guard.assert_not_called()
        delete_guards.assert_not_called()
        cable_guard.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                         the resolved type reaches every check                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _held_type(type_id: int = TYPE_ID) -> MagicMock:
    """A CmdbType the delete route already resolved"""
    held = MagicMock()
    held.public_id = type_id

    return held


class TestTheResolvedTypeIsHandedOn:
    """Both IPAM checks of every target get its type from the caller's map"""

    def test_each_target_gets_its_own_type(self) -> None:
        """Two targets of two types, each check sees the matching one"""
        first, second = _held_type(TYPE_ID), _held_type(OTHER_TYPE_ID)
        targets: list[dict[str, Any]] = [
            {'public_id': 1, 'type_id': TYPE_ID}, {'public_id': 2, 'type_id': OTHER_TYPE_ID},
        ]

        with patch(f'{GUARD_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[]) as delete_guards, \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete'):
            guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), targets,
                                 {TYPE_ID: first, OTHER_TYPE_ID: second})

        assert [call.args[3] for call in license_guard.call_args_list] == [first, second]
        assert [call.args[3] for call in delete_guards.call_args_list] == [first, second]

    def test_a_target_whose_type_is_not_held_gets_none(self) -> None:
        """The checks then read it as before"""
        with patch(f'{GUARD_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{GUARD_PATH}.selection_ipam_type_ids', return_value=SELECTION_TYPE_IDS), \
             patch(f'{GUARD_PATH}.enforce_delete_guards', return_value=[]) as delete_guards, \
             patch(f'{GUARD_PATH}.guard_cable_objects_delete'):
            guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), [{'public_id': 1, 'type_id': TYPE_ID}])

        assert license_guard.call_args.args[3] is None
        assert delete_guards.call_args.args[3] is None

    def test_the_single_delete_hands_its_type_as_a_one_entry_map(self) -> None:
        """The single route's one read reaches the batched guard"""
        held = _held_type()

        with patch(f'{GUARD_PATH}.guard_objects_delete') as batched:
            guard_object_delete(MagicMock(), MagicMock(), MagicMock(), {'public_id': 1, 'type_id': TYPE_ID}, held)

        assert batched.call_args.args[4] == {TYPE_ID: held}

    def test_the_licence_question_takes_the_type(self) -> None:
        """object_delete_requires_ipam_license is asked with it"""
        held = _held_type()

        with patch(f'{GUARD_PATH}.object_delete_requires_ipam_license', return_value=False) as asked:
            guard_object_delete_license(MagicMock(), MagicMock(), {'type_id': TYPE_ID}, held)

        assert asked.call_args.args[2] is held

