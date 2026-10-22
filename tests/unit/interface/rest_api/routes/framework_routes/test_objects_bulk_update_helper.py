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
Unit tests for the bulk object update (cmdb_objects.objects_bulk_update_helper)

The selection reader (duplicates, the cap, the fallback, the PATCH's required objectIDs), the two payload builders
(the PUT's stored-field guard, the PATCH's merge) and the all-or-nothing orchestration: every target is written
before any is finished, and a failure undoes the writes before it through the real WriteLedger
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException, NotFound

import cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_update_helper as bulk_update_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_update_helper import (
    apply_object_updates,
    bulk_patch_payload,
    complete_put_payload,
    guard_put_keeps_stored_fields,
    read_bulk_update_targets,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import MAX_BULK_UPDATE_OBJECTS
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_update_helper'

PATH_ID: int = 5
FIRST_ID: int = 11
SECOND_ID: int = 12
THIRD_ID: int = 13
HTTP_BAD_REQUEST: int = 400
HTTP_INTERNAL_SERVER_ERROR: int = 500
PAYLOAD: dict[str, Any] = {'type_id': 1, 'fields': []}
PRIOR_DOCUMENT: dict[str, Any] = {'public_id': FIRST_ID, 'fields': [{'name': 'a', 'value': 'before'}]}


class TestReadBulkUpdateTargets:
    """What a bulk update targets."""

    def test_without_object_ids_the_path_id_is_the_target(self) -> None:
        """No objectIDs: the route's own object"""
        assert read_bulk_update_targets([], PATH_ID) == [PATH_ID]

    def test_the_ids_keep_their_order(self) -> None:
        """Repeated parameters, read as given"""
        assert read_bulk_update_targets([str(SECOND_ID), str(FIRST_ID)], PATH_ID) == [SECOND_ID, FIRST_ID]

    def test_a_repeated_id_is_one_target_at_its_first_place(self) -> None:
        """Duplicates go, the first occurrence stays where it was"""
        raw: list[str] = [str(SECOND_ID), str(FIRST_ID), str(SECOND_ID), str(FIRST_ID)]

        assert read_bulk_update_targets(raw, PATH_ID) == [SECOND_ID, FIRST_ID]

    @pytest.mark.parametrize('raw', ['abc', '0', '-1', '1,2'], ids=['text', 'zero', 'negative', 'comma-joined'])
    def test_an_unusable_id_is_a_400(self, raw: str) -> None:
        """The shared public_id reader refuses it - a comma-joined value is one unusable id"""
        with pytest.raises(HTTPException) as exc_info:
            read_bulk_update_targets([raw], PATH_ID)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_exactly_the_cap_is_allowed(self) -> None:
        """MAX_BULK_UPDATE_OBJECTS distinct ids pass"""
        raw: list[str] = [str(public_id) for public_id in range(1, MAX_BULK_UPDATE_OBJECTS + 1)]

        assert len(read_bulk_update_targets(raw, PATH_ID)) == MAX_BULK_UPDATE_OBJECTS

    def test_one_past_the_cap_is_a_400_naming_both_numbers(self) -> None:
        """The count is of distinct ids, and the message says how many were sent and how many may be"""
        raw: list[str] = [str(public_id) for public_id in range(1, MAX_BULK_UPDATE_OBJECTS + 2)]

        with pytest.raises(HTTPException) as exc_info:
            read_bulk_update_targets(raw, PATH_ID)

        assert exc_info.value.code == HTTP_BAD_REQUEST
        assert str(MAX_BULK_UPDATE_OBJECTS) in exc_info.value.description
        assert str(MAX_BULK_UPDATE_OBJECTS + 1) in exc_info.value.description

    def test_duplicates_do_not_count_towards_the_cap(self) -> None:
        """The cap's own number of ids, each named twice, still passes"""
        raw: list[str] = [str(public_id) for public_id in range(1, MAX_BULK_UPDATE_OBJECTS + 1)] * 2

        assert len(read_bulk_update_targets(raw, PATH_ID)) == MAX_BULK_UPDATE_OBJECTS


class TestApplyObjectUpdates:
    """All targets or none."""

    def test_every_target_is_written_before_any_is_finished(self) -> None:
        """The writes in target order, then the finishes in target order, answering one document per target"""
        recorder = MagicMock()
        written = {FIRST_ID: MagicMock(name='first'), SECOND_ID: MagicMock(name='second')}
        recorder.write.side_effect = lambda object_id, *_args: written[object_id]
        recorder.finish.side_effect = lambda entry, _context: {'written': entry}
        context = MagicMock()

        with patch(f'{HELPER_PATH}.write_object_update', recorder.write), \
             patch(f'{HELPER_PATH}.finish_object_update', recorder.finish):
            results = apply_object_updates([FIRST_ID, SECOND_ID], PAYLOAD, True, context)

        assert [name for name, _args, _kwargs in recorder.mock_calls] == ['write', 'write', 'finish', 'finish']
        assert results == [{'written': written[FIRST_ID]}, {'written': written[SECOND_ID]}]

    def test_every_write_gets_the_same_ledger_and_the_shared_payload(self) -> None:
        """One ledger for the request; the payload and the active flag are handed to every target as they came"""
        write = MagicMock()
        context = MagicMock()

        with patch(f'{HELPER_PATH}.write_object_update', write), patch(f'{HELPER_PATH}.finish_object_update'):
            apply_object_updates([FIRST_ID, SECOND_ID], PAYLOAD, False, context)

        ledgers = {id(recorded.args[4]) for recorded in write.call_args_list}
        assert len(ledgers) == 1
        assert [recorded.args[:4] for recorded in write.call_args_list] == [
            (FIRST_ID, PAYLOAD, False, context), (SECOND_ID, PAYLOAD, False, context),
        ]

    def test_a_refused_target_undoes_the_earlier_writes_and_finishes_none(self) -> None:
        """The second target's 404 restores the first from its snapshot and is the request's answer"""
        manager = MagicMock()
        manager.get_one_by.return_value = PRIOR_DOCUMENT
        finish = MagicMock()

        def _write(object_id: int, _payload: Any, _active: Any, _context: Any, ledger: Any) -> MagicMock:
            if object_id == SECOND_ID:
                raise NotFound(f'Object with ID:{object_id} not found!')
            ledger.updated(manager, object_id, PRIOR_DOCUMENT)
            return MagicMock()

        with patch(f'{HELPER_PATH}.write_object_update', side_effect=_write), \
             patch(f'{HELPER_PATH}.finish_object_update', finish):
            with pytest.raises(NotFound):
                apply_object_updates([FIRST_ID, SECOND_ID, THIRD_ID], PAYLOAD, None, MagicMock())

        manager.replace.assert_called_once_with(FIRST_ID, PRIOR_DOCUMENT)
        finish.assert_not_called()

    def test_an_undo_that_cannot_finish_is_a_500_naming_the_object(self) -> None:
        """The snapshot could not be put back: the residue message, not the target's own error"""
        manager = MagicMock()
        manager.collection = 'framework.objects'
        manager.get_one_by.return_value = {'public_id': FIRST_ID, 'fields': 'still the new values'}

        def _write(object_id: int, _payload: Any, _active: Any, _context: Any, ledger: Any) -> MagicMock:
            if object_id == SECOND_ID:
                raise NotFound('gone')
            ledger.updated(manager, object_id, PRIOR_DOCUMENT)
            return MagicMock()

        with patch(f'{HELPER_PATH}.write_object_update', side_effect=_write), \
             patch(f'{HELPER_PATH}.finish_object_update'):
            with pytest.raises(HTTPException) as exc_info:
                apply_object_updates([FIRST_ID, SECOND_ID], PAYLOAD, None, MagicMock())

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR
        assert str(FIRST_ID) in exc_info.value.description

    def test_a_failed_finish_does_not_undo_the_writes(self) -> None:
        """Once every target is written the ledger is closed: a consequence failing later leaves the writes"""
        manager = MagicMock()

        def _write(object_id: int, _payload: Any, _active: Any, _context: Any, ledger: Any) -> MagicMock:
            ledger.updated(manager, object_id, PRIOR_DOCUMENT)
            return MagicMock()

        with patch(f'{HELPER_PATH}.write_object_update', side_effect=_write), \
             patch(f'{HELPER_PATH}.finish_object_update', side_effect=RuntimeError('mirror failed')):
            with pytest.raises(RuntimeError):
                apply_object_updates([FIRST_ID], PAYLOAD, None, MagicMock())

        manager.replace.assert_not_called()


def test_the_cap_is_the_shared_bulk_bound() -> None:
    """The module reads the constant the routes document"""
    assert bulk_update_helper.MAX_BULK_UPDATE_OBJECTS == MAX_BULK_UPDATE_OBJECTS


def test_without_object_ids_and_without_a_fallback_it_is_a_400() -> None:
    """The bulk PATCH has no path id: objectIDs is required"""
    with pytest.raises(HTTPException) as exc_info:
        read_bulk_update_targets([], None)

    assert exc_info.value.code == HTTP_BAD_REQUEST
    assert 'objectIDs' in exc_info.value.description


DECLARED_A: str = 'a'
DECLARED_B: str = 'b'
STALE_NAME: str = 'stale'


def _stored(*names: str) -> MagicMock:
    """A stored CmdbObject stand-in carrying fields with these names"""
    stored = MagicMock()
    stored.fields = [{'name': name, 'value': f'stored-{name}'} for name in names]
    stored.get_public_id.return_value = FIRST_ID

    return stored


def _type(*names: str) -> MagicMock:
    """A CmdbType stand-in declaring fields with these names"""
    declared = MagicMock()
    declared.get_fields.return_value = [{'name': name} for name in names]
    declared.get_mds_section_ids.return_value = {'mds'}

    return declared


class TestGuardPutKeepsStoredFields:
    """Q2: a full-object PUT carries every field the object stores and its type declares"""

    def test_every_stored_field_carried_passes(self) -> None:
        """Values may differ - only presence counts"""
        payload = {'fields': [{'name': DECLARED_A, 'value': 1}, {'name': DECLARED_B, 'value': 2}]}

        guard_put_keeps_stored_fields(payload, _stored(DECLARED_A, DECLARED_B), _type(DECLARED_A, DECLARED_B))

    def test_a_dropped_field_is_a_400_naming_it_and_the_object(self) -> None:
        """The message names what would be lost and points at PATCH"""
        with pytest.raises(HTTPException) as exc_info:
            guard_put_keeps_stored_fields(
                {'fields': [{'name': DECLARED_A, 'value': 1}]},
                _stored(DECLARED_A, DECLARED_B), _type(DECLARED_A, DECLARED_B),
            )

        assert exc_info.value.code == HTTP_BAD_REQUEST
        assert DECLARED_B in exc_info.value.description
        assert str(FIRST_ID) in exc_info.value.description
        assert 'PATCH' in exc_info.value.description

    @pytest.mark.parametrize('payload', [{}, {'fields': None}, {'fields': []}], ids=['absent', 'null', 'empty'])
    def test_no_fields_at_all_drops_everything(self, payload: dict[str, Any]) -> None:
        """A PUT without fields would empty the object"""
        with pytest.raises(HTTPException):
            guard_put_keeps_stored_fields(payload, _stored(DECLARED_A), _type(DECLARED_A))

    def test_a_stale_field_the_type_no_longer_declares_may_go(self) -> None:
        """Dropping a stale name is what every update does"""
        payload = {'fields': [{'name': DECLARED_A, 'value': 1}]}

        guard_put_keeps_stored_fields(payload, _stored(DECLARED_A, STALE_NAME), _type(DECLARED_A))

    def test_a_declared_field_the_object_never_stored_is_not_required(self) -> None:
        """Only what is stored can be lost"""
        payload = {'fields': [{'name': DECLARED_A, 'value': 1}]}

        guard_put_keeps_stored_fields(payload, _stored(DECLARED_A), _type(DECLARED_A, DECLARED_B))


class TestPayloadBuilders:
    """What each target is written with"""

    def test_a_put_answers_its_payload_after_the_guard(self) -> None:
        """The same object for every target"""
        payload = {'fields': [{'name': DECLARED_A, 'value': 1}]}

        assert complete_put_payload(payload)(_stored(DECLARED_A), _type(DECLARED_A)) is payload

    def test_a_put_that_drops_a_field_is_refused_by_the_builder(self) -> None:
        """The guard runs per target, against that target"""
        builder = complete_put_payload({'fields': []})

        with pytest.raises(HTTPException):
            builder(_stored(DECLARED_A), _type(DECLARED_A))

    def test_a_patch_merges_its_subset_into_each_target(self) -> None:
        """build_patched_object_data with the target, the subset and the type's sections - active left out"""
        stored, declared = _stored(DECLARED_A), _type(DECLARED_A)
        patch_body = {'fields': [{'name': DECLARED_A, 'value': 1}], 'comment': 'c', 'active': False}

        with patch(f'{HELPER_PATH}.build_patched_object_data') as merge:
            result = bulk_patch_payload(patch_body)(stored, declared)

        merge.assert_called_once_with(stored, {'fields': [{'name': DECLARED_A, 'value': 1}], 'comment': 'c'},
                                      {'mds'})
        assert result is merge.return_value

    def test_a_patch_keeps_every_field_it_does_not_name(self) -> None:
        """The real merge: one stored field changed, the other as stored"""
        stored = CmdbObject(
            public_id=FIRST_ID, type_id=1, author_id=1, version='1.0.0', active=True,
            fields=[{'name': DECLARED_A, 'value': 'old', 'type': 'text'},
                    {'name': DECLARED_B, 'value': 'kept', 'type': 'text'}],
            multi_data_sections=[],
        )

        merged = bulk_patch_payload({'fields': [{'name': DECLARED_A, 'value': 'new'}]})(stored, _type(DECLARED_A))

        assert {field['name']: field['value'] for field in merged['fields']} == {DECLARED_A: 'new', DECLARED_B: 'kept'}
