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
Unit tests for the steps apply_object_update runs (cmdb_objects.objects_helper)

`_build_update_candidate` stamps the server-owned values and takes the transient ones off,
`_prepare_location_change` validates a placement only when the candidate has a location field,
`_validate_update_candidate` runs every pre-write check in order and `_run_update_consequences` mirrors the
location and the Rack state after the write. The orchestrator's own order is pinned in test_objects_helper
"""
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    _build_update_candidate,
    _prepare_location_change,
    _run_update_consequences,
    _validate_update_candidate,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import (
    LocationChange,
    ObjectWriteContext,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper'

OBJECT_ID: int = 5
EDITOR_ID: int = 77
STORED_AUTHOR_ID: int = 3
STORED_VERSION: str = '1.0.0'
PAYLOAD_VERSION: str = '1.0.4'
LOCATION_PARENT_ID: int = 42
UPDATE_COMMENT: str = 'why'
LOCATION_NAME: str = 'Row 4'


def _stored(active: bool = True) -> SimpleNamespace:
    """The stored object, as far as the candidate build reads it."""
    return SimpleNamespace(
        creation_time=datetime(2025, 1, 1), author_id=STORED_AUTHOR_ID, active=active, version=STORED_VERSION,
    )


def _context() -> ObjectWriteContext:
    """A context of MagicMock handles, the caller carrying an id."""
    return ObjectWriteContext(SimpleNamespace(public_id=EDITOR_ID), MagicMock(), MagicMock(), MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _build_update_candidate                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildUpdateCandidate:
    """The candidate: a copy of the payload with the server-owned values stamped and the transient ones off."""

    def test_the_transient_values_are_returned_not_kept(self) -> None:
        """comment and location_name come back separately and are not in the candidate"""
        payload = {'fields': [], 'comment': UPDATE_COMMENT, 'location_name': LOCATION_NAME}

        candidate, comment, location_name = _build_update_candidate(
            OBJECT_ID, payload, None, _stored(), SimpleNamespace(public_id=EDITOR_ID),
        )

        assert (comment, location_name) == (UPDATE_COMMENT, LOCATION_NAME)
        assert 'comment' not in candidate and 'location_name' not in candidate

    def test_without_transient_values_the_defaults_come_back(self) -> None:
        """No comment is the empty string, no location name is None"""
        _candidate, comment, location_name = _build_update_candidate(
            OBJECT_ID, {'fields': []}, None, _stored(), SimpleNamespace(public_id=EDITOR_ID),
        )

        assert (comment, location_name) == ('', None)

    def test_the_payload_is_copied_deeply(self) -> None:
        """Changing the candidate's nested fields leaves the shared payload alone"""
        payload: dict[str, Any] = {'fields': [{'name': 'a', 'value': 1}]}

        candidate, _comment, _name = _build_update_candidate(
            OBJECT_ID, payload, None, _stored(), SimpleNamespace(public_id=EDITOR_ID),
        )
        candidate['fields'][0]['value'] = 2

        assert payload == {'fields': [{'name': 'a', 'value': 1}]}

    def test_the_version_starts_from_the_payload_or_the_stored_one(self) -> None:
        """The payload's version wins; without one the stored version is the base for the bump"""
        with_version, _c, _n = _build_update_candidate(
            OBJECT_ID, {'version': PAYLOAD_VERSION}, None, _stored(), SimpleNamespace(public_id=EDITOR_ID),
        )
        without_version, _c, _n = _build_update_candidate(
            OBJECT_ID, {}, None, _stored(), SimpleNamespace(public_id=EDITOR_ID),
        )

        assert with_version['version'] == PAYLOAD_VERSION
        assert without_version['version'] == STORED_VERSION


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _prepare_location_change                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPrepareLocationChange:
    """A placement is validated only for a candidate that carries a location field."""

    def test_no_location_field_needs_no_manager(self) -> None:
        """None comes back, and no locations manager is resolved"""
        with patch(f'{HELPER_PATH}.extract_object_location_parent', return_value=(False, None)), \
             patch(f'{HELPER_PATH}.ManagerProvider') as provider, \
             patch(f'{HELPER_PATH}.validate_object_location_change') as validate:
            assert _prepare_location_change(OBJECT_ID, {'fields': []}, MagicMock()) is None

        provider.get_manager.assert_not_called()
        validate.assert_not_called()

    @pytest.mark.parametrize('parent', [LOCATION_PARENT_ID, None], ids=['placed', 'cleared'])
    def test_a_location_field_is_validated_and_returned(self, parent: int | None) -> None:
        """Validated against the tree and the Rack rules, with the one manager returned for the mirror"""
        request_user = MagicMock()
        locations_manager = MagicMock()

        with patch(f'{HELPER_PATH}.extract_object_location_parent', return_value=(True, parent)), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager), \
             patch(f'{HELPER_PATH}.validate_object_location_change') as validate, \
             patch(f'{HELPER_PATH}.guard_rack_location_change') as rack_guard:
            change = _prepare_location_change(OBJECT_ID, {'fields': []}, request_user)

        assert change == LocationChange(parent, locations_manager)
        validate.assert_called_once_with(OBJECT_ID, parent, locations_manager)
        rack_guard.assert_called_once_with(request_user, OBJECT_ID, parent, locations_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _validate_update_candidate                                               #
# -------------------------------------------------------------------------------------------------------------------- #
VALIDATION_STEPS: tuple[str, ...] = (
    'validate_and_fill_object_fields',
    'validate_required_object_fields',
    'validate_object_field_values',
    '_prepare_location_change',
    'guard_object_write_license',
    'enforce_object_write_invariants',
    'guard_predefined_select_options',
)


def _validate(invariant_error: str | None = None) -> tuple[MagicMock, Any]:
    """Runs _validate_update_candidate with every check recorded; returns the recorder and the result."""
    recorder = MagicMock()
    patches = []

    for step in VALIDATION_STEPS:
        value = invariant_error if step == 'enforce_object_write_invariants' else None
        mock = MagicMock(return_value=value)
        recorder.attach_mock(mock, step)
        patches.append(patch(f'{HELPER_PATH}.{step}', mock))

    for active in patches:
        active.start()

    try:
        result = _validate_update_candidate(OBJECT_ID, {'fields': []}, MagicMock(), {}, _context())
    finally:
        for active in reversed(patches):
            active.stop()

    return recorder, result


def test_every_check_runs_in_order() -> None:
    """Field checks, the placement, the licence, the invariants, then the predefined select options"""
    recorder, _result = _validate()

    assert [name for name, _args, _kwargs in recorder.mock_calls] == list(VALIDATION_STEPS)


def test_an_invariant_error_is_a_400_and_stops_before_the_select_check() -> None:
    """The invariant's message is the answer, and the remaining check never runs"""
    with pytest.raises(HTTPException) as exc_info:
        _validate('a broken invariant')

    assert exc_info.value.code == 400
    assert exc_info.value.description == 'a broken invariant'


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _run_update_consequences                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
CONSEQUENCE_STEPS: tuple[str, ...] = (
    'sync_object_location',
    'handle_rack_object_updated',
    'reconcile_object_rack_membership',
)


def _consequences(location_change: LocationChange | None) -> MagicMock:
    """Runs _run_update_consequences with every step recorded; returns the recorder."""
    recorder = MagicMock()
    patches = []

    for step in CONSEQUENCE_STEPS:
        mock = MagicMock()
        recorder.attach_mock(mock, step)
        patches.append(patch(f'{HELPER_PATH}.{step}', mock))

    for active in patches:
        active.start()

    try:
        _run_update_consequences(OBJECT_ID, {}, {}, MagicMock(), location_change, LOCATION_NAME, _context())
    finally:
        for active in reversed(patches):
            active.stop()

    return recorder


def test_with_a_location_the_mirror_runs_before_the_rack_consequences() -> None:
    """Location mirror, Rack consequences, then the Rack membership the location implies"""
    locations_manager = MagicMock()
    recorder = _consequences(LocationChange(LOCATION_PARENT_ID, locations_manager))

    assert [name for name, _args, _kwargs in recorder.mock_calls] == list(CONSEQUENCE_STEPS)
    assert recorder.sync_object_location.call_args.args[1:3] == (LOCATION_PARENT_ID, LOCATION_NAME)
    assert recorder.handle_rack_object_updated.call_args.args[-1] is locations_manager
    assert recorder.reconcile_object_rack_membership.call_args.args[2] == LOCATION_PARENT_ID


def test_without_a_location_only_the_rack_consequences_run() -> None:
    """No mirror, no membership - and the Rack step gets no locations manager"""
    recorder = _consequences(None)

    assert [name for name, _args, _kwargs in recorder.mock_calls] == ['handle_rack_object_updated']
    assert recorder.handle_rack_object_updated.call_args.args[-1] is None
