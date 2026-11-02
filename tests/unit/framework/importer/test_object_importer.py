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
Unit tests for cmdb.framework.importer.importers.object_importer

DB-free: a real importer runs over a mocked ObjectsManager, with ``current_app``, the validator, the writers
(``insert_new_objects``, ``plan_overwrite``, ``replace_stored_object``) and the portal-sync helper patched at the
module path; a few tests drive a method on a MagicMock-typed ``self``. The writers themselves are tested against
real documents in ``test_object_import_writer.py``.

Covers the import pipeline (``_import``): the report in file order, an unexpected per-object error failing
only that object, start_element + max_elements, one sync per batch; the rows carrying a public_id (one read
of the stored objects, an overwrite as one replace and no delete, both types guarded, an object gone before the
replace imported under its id, the compatibility check, the type read once per import, a file naming an id
twice, a failed or interrupted write reported as itself, the write before the new rows); the new rows (one guard,
chunked writes, per-object refusals, the public_id clash retried with a drawn id, a chunk that fails as a whole
read back); and the cloud ConfigItem limit (the user's own rule, 0 as a literal limit, one count per import kept
current by the import's inserts and failed inserts, an overwrite never asked).
"""
from itertools import count
from types import SimpleNamespace
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.framework.importer.importer_constants import CONFIG_ITEM_LIMIT_REACHED_MESSAGE
from cmdb.models.user_model import CmdbUser
from cmdb.framework.importer.helper.object_import_validator import ImportTypeContext
from cmdb.framework.object_field_value_rules import FieldValueRule
from cmdb.models.type_model import TEXT_VALUE_MAX_LENGTH
from cmdb.errors.database import DocumentInsertDuplicateKeyError, DocumentInsertError, DocumentNetworkError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerInsertError
from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerGetError,
    ObjectsManagerInsertError,
    ObjectsManagerUpdateError,
)
from cmdb.models.object_model.object_constants import ObjectWriteVerb
# -------------------------------------------------------------------------------------------------------------------- #
# The suite drives the class-under-test's protected methods directly on a MagicMock ``self``
# pylint: disable=protected-access

PATH: str = 'cmdb.framework.importer.importers.object_importer'
NEW_OBJECT_FIRST_ID: int = 100
RETRIED_ID: int = 500
OVERWRITTEN_ID: int = 7
TARGET_TYPE_ID: int = 9
OTHER_TYPE_ID: int = 11
FIELD_A: str = 'a'
FIELD_B: str = 'b'
LIMIT: int = 10
FREE_SLOTS: int = 2
CHUNK_OF_TWO: int = 2
OVERWRITE_DIFF: dict = {'old': [{'name': FIELD_A, 'value': 'stored'}], 'new': [{'name': FIELD_A, 'value': 'x'}]}


def _run_config(start_element: int = 0, max_elements: int = 0, overwrite_public: bool = True) -> SimpleNamespace:
    """A minimal run config for the import loop."""
    return SimpleNamespace(
        start_element=start_element,
        max_elements=max_elements,
        overwrite_public=overwrite_public,
    )


def _target_type(fields: list[str] | None = None) -> MagicMock:
    """The import's target type, with the given field names"""
    target = MagicMock()
    target.public_id = TARGET_TYPE_ID
    target.get_fields.return_value = [{'name': name} for name in fields or [FIELD_A]]

    return target


def _importer(run_config: SimpleNamespace | None = None, stored: list[dict] | None = None,
              stored_count: int = 0, limit: int | None = LIMIT) -> ObjectImporter:
    """
    A real ObjectImporter over a mocked ObjectsManager

    Built without __init__ (which needs a file and a parser); only the attributes the pipeline reads are set.
    The manager answers ``stored`` for the overwrite read, the target type for the guard, and an insert answers
    the id the object carries (or the next drawn one)
    """
    importer: ObjectImporter = ObjectImporter.__new__(ObjectImporter)
    importer.objects_manager = MagicMock()
    importer.objects_manager.find_objects.return_value = stored or []
    importer.objects_manager.count_documents.return_value = stored_count
    drawn_ids = count(NEW_OBJECT_FIRST_ID)
    importer.objects_manager.insert_object.side_effect = (
        lambda document, **_kwargs: document.get('public_id') or next(drawn_ids)
    )
    importer.request_user = CmdbUser(public_id=1, user_name='importer', active=True, config_items_limit=limit)
    importer.target_type = _target_type()
    importer.objects_manager.guard_writable_type.return_value = importer.target_type
    importer._object_count = None
    importer._types = {}
    importer.get_config = lambda: run_config or _run_config()

    return importer


def _new_row(name: str = 'row') -> tuple[dict, dict]:
    """A (provided, generated) pair without a public_id"""
    return {'name': name}, {'type_id': TARGET_TYPE_ID, 'fields': [{'name': FIELD_A, 'value': name}]}


def _id_row(public_id: int, fields: list[str] | None = None) -> tuple[dict, dict]:
    """A (provided, generated) pair carrying a public_id"""
    return ({'public_id': public_id},
            {'public_id': public_id, 'type_id': TARGET_TYPE_ID,
             'fields': [{'name': name, 'value': 'x'} for name in fields or [FIELD_A]]})


def _stored(public_id: int, type_id: int = TARGET_TYPE_ID) -> dict:
    """An object document as stored"""
    return {'public_id': public_id, 'type_id': type_id, 'fields': []}


class _Writer:
    """Stands in for ``insert_new_objects``: assigns ids in order, records each call, answers set failures"""

    def __init__(self, failures: dict[int, Exception] | None = None, error: Exception | None = None) -> None:
        self.calls: list[list[dict]] = []
        self.failures = failures or {}
        self.error = error
        self.ids = count(NEW_OBJECT_FIRST_ID)

    def __call__(self, _manager: object, documents: list[dict]) -> dict[int, Exception]:
        self.calls.append(list(documents))
        for document in documents:
            document['public_id'] = next(self.ids)
        if self.error is not None:
            raise self.error
        return self.failures


class _Overwriter:
    """
    Stands in for ``plan_overwrite`` + ``replace_stored_object``: records both, answers the set outcome

    The planned document is a copy of the imported one marked as planned, so a test can tell which one was written
    """

    def __init__(self, matched: bool = True, error: Exception | None = None) -> None:
        self.planned: list[tuple[dict, dict]] = []
        self.replaced: list[dict] = []
        self.matched = matched
        self.error = error

    def plan(self, stored: dict, imported: dict, _user: CmdbUser) -> tuple[dict, dict]:
        """Records the pair and answers a marked copy with a fixed diff"""
        self.planned.append((stored, imported))
        return {**imported, 'planned': True}, OVERWRITE_DIFF

    def replace(self, _manager: object, document: dict) -> bool:
        """Records the document and answers the set outcome"""
        self.replaced.append(document)
        if self.error is not None:
            raise self.error
        return self.matched


def _run(importer: ObjectImporter, candidates: list, writer: _Writer | None = None, cloud_mode: bool = False,
         errors: Callable[[dict], list] | None = None, overwriter: _Overwriter | None = None):
    """Runs ``_import`` with the validator, the writers, current_app and the sync patched"""
    overwriter = overwriter or _Overwriter()

    with patch(f'{PATH}.current_app') as current_app, \
            patch(f'{PATH}.normalize_and_validate_object',
                  side_effect=lambda obj, *_args: (errors or (lambda _obj: []))(obj)), \
            patch(f'{PATH}.insert_new_objects', side_effect=writer or _Writer()), \
            patch(f'{PATH}.plan_overwrite', side_effect=overwriter.plan), \
            patch(f'{PATH}.replace_stored_object', side_effect=overwriter.replace), \
            patch(f'{PATH}.handle_sync_config_item_count'):
        current_app.cloud_mode = cloud_mode
        return importer._import(candidates, None)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     _import                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImportBatch:
    """The pipeline reports every row once, in file order, and syncs once."""

    def test_the_report_keeps_the_file_order(self) -> None:
        """Successes and failures each come back in the order of the file"""
        importer = _importer()
        candidates = [_new_row('a'), _new_row('bad'), _new_row('c')]

        result = _run(importer, candidates,
                      errors=lambda obj: ['bad'] if obj['fields'][0]['value'] == 'bad' else [])

        assert [message.public_id for message in result.success_imports] == [NEW_OBJECT_FIRST_ID,
                                                                             NEW_OBJECT_FIRST_ID + 1]
        assert [message.failed_object for message in result.failed_imports] == [{'name': 'bad'}]
        assert result.message == 'Imported 2 of 3 objects, 1 failed'

    def test_an_unexpected_error_fails_only_that_object(self) -> None:
        """An error nobody anticipated is reported for its object; the batch keeps importing."""
        importer = _importer()

        def _errors(obj: dict) -> list:
            if obj['fields'][0]['value'] == 'boom':
                raise AttributeError('boom')
            return []

        result = _run(importer, [_new_row('a'), _new_row('boom'), _new_row('c')], errors=_errors)

        assert len(result.success_imports) == 2  # the objects around it still got written
        assert result.failed_imports[0].errors == ['Unexpected error while importing this object: boom']
        assert result.failed_imports[0].failed_object == {'name': 'boom'}

    @pytest.mark.parametrize('cloud_mode', [True, False], ids=['cloud', 'on-premise'])
    def test_syncs_once_when_anything_was_written(self, cloud_mode: bool) -> None:
        """A single config-item sync runs when at least one object was written"""
        importer = _importer()

        with patch(f'{PATH}.current_app') as current_app, \
                patch(f'{PATH}.normalize_and_validate_object', return_value=[]), \
                patch(f'{PATH}.insert_new_objects', side_effect=_Writer()), \
                patch(f'{PATH}.handle_sync_config_item_count') as sync:
            current_app.cloud_mode = cloud_mode
            importer._import([_new_row(), _new_row()], None)

        sync.assert_called_once_with(importer.request_user)

    def test_no_sync_when_nothing_was_written(self) -> None:
        """No config-item sync runs when every candidate failed."""
        importer = _importer()

        with patch(f'{PATH}.current_app'), \
                patch(f'{PATH}.normalize_and_validate_object', return_value=['bad']), \
                patch(f'{PATH}.handle_sync_config_item_count') as sync:
            importer._import([_new_row()], None)

        sync.assert_not_called()

    def test_a_bug_in_the_sync_is_not_swallowed(self) -> None:
        """The sync handles its own failures; a programming error reaches the caller"""
        importer = _importer()

        with patch(f'{PATH}.current_app') as current_app, \
                patch(f'{PATH}.normalize_and_validate_object', return_value=[]), \
                patch(f'{PATH}.insert_new_objects', side_effect=_Writer()), \
                patch(f'{PATH}.handle_sync_config_item_count', side_effect=TypeError('bug')):
            current_app.cloud_mode = False
            with pytest.raises(TypeError):
                importer._import([_new_row()], None)

    def test_start_element_skips_leading_objects(self) -> None:
        """start_element offsets the first processed object."""
        writer = _Writer()

        result = _run(_importer(_run_config(start_element=2)), [_new_row('a'), _new_row('b'), _new_row('c')],
                      writer)

        assert len(result.success_imports) == 1
        assert [document['fields'][0]['value'] for document in writer.calls[0]] == ['c']

    def test_max_elements_limits_the_batch(self) -> None:
        """max_elements caps the number of processed candidates (count, not absolute index)."""
        writer = _Writer()

        result = _run(_importer(_run_config(start_element=1, max_elements=2)),
                      [_new_row(str(index)) for index in range(5)], writer)

        assert len(result.success_imports) == 2
        assert [document['fields'][0]['value'] for document in writer.calls[0]] == ['1', '2']

    def test_overwrite_off_imports_a_row_with_an_id_as_new(self) -> None:
        """With overwrite disabled the public_id is dropped, so the row joins the new objects"""
        importer = _importer(_run_config(overwrite_public=False))
        writer = _Writer()

        result = _run(importer, [_id_row(OVERWRITTEN_ID)], writer)

        assert result.success_imports[0].public_id == NEW_OBJECT_FIRST_ID
        importer.objects_manager.find_objects.assert_not_called()
        importer.objects_manager.insert_object.assert_not_called()

    def test_the_rows_with_an_id_are_written_before_the_new_rows(self) -> None:
        """The counter is raised past the file's own ids before a block is reserved for the new rows"""
        importer = _importer()
        order: list[str] = []
        importer.objects_manager.insert_object.side_effect = lambda document, **_kw: order.append('id') or 1
        writer = _Writer()
        original_call = writer.__call__

        def _recording(manager: object, documents: list[dict]) -> dict:
            order.append('new')
            return original_call(manager, documents)

        with patch(f'{PATH}.current_app') as current_app, \
                patch(f'{PATH}.normalize_and_validate_object', return_value=[]), \
                patch(f'{PATH}.insert_new_objects', side_effect=_recording), \
                patch(f'{PATH}.handle_sync_config_item_count'):
            current_app.cloud_mode = False
            importer._import([_new_row(), _id_row(OVERWRITTEN_ID)], None)

        assert order == ['id', 'new']


class TestRowsWithId:
    """The rows carrying a public_id: one read of what is stored, then one write per row in file order."""

    def test_the_stored_objects_are_read_with_one_query(self) -> None:
        """Every row's id in one $in read, as documents"""
        importer = _importer()

        _run(importer, [_id_row(OVERWRITTEN_ID), _id_row(OVERWRITTEN_ID + 1)])

        importer.objects_manager.find_objects.assert_called_once_with(
            {'public_id': {'$in': [OVERWRITTEN_ID, OVERWRITTEN_ID + 1]}}, as_dict=True,
        )

    def test_an_unused_id_is_imported_as_it_is(self) -> None:
        """Nothing to overwrite: the object is inserted under its id, with the known target type"""
        importer = _importer()

        overwriter = _Overwriter()

        result = _run(importer, [_id_row(OVERWRITTEN_ID)], overwriter=overwriter)

        assert result.success_imports[0].public_id == OVERWRITTEN_ID
        assert result.success_imports[0].overwritten is False
        assert not overwriter.replaced
        assert importer.objects_manager.insert_object.call_args.kwargs == {'object_type': importer.target_type}

    def test_an_existing_object_is_replaced_in_place(self) -> None:
        """One replace of the planned document; nothing is deleted or inserted, and no type is read again"""
        stored = _stored(OVERWRITTEN_ID)
        importer = _importer(stored=[stored])
        overwriter = _Overwriter()
        row = _id_row(OVERWRITTEN_ID)

        result = _run(importer, [row], overwriter=overwriter)

        assert result.failed_imports == []
        assert overwriter.planned == [(stored, row[1])]
        assert overwriter.replaced == [{**row[1], 'planned': True}]
        importer.objects_manager.delete_with_follow_up.assert_not_called()
        importer.objects_manager.delete_object.assert_not_called()
        importer.objects_manager.insert_object.assert_not_called()
        importer.objects_manager.get_object_type.assert_not_called()

    def test_an_overwrite_reports_the_written_document_and_its_diff(self) -> None:
        """The success carries what was stored and the diff, so the route logs it as an EDIT"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)])

        success = _run(importer, [_id_row(OVERWRITTEN_ID)]).success_imports[0]

        assert success.public_id == OVERWRITTEN_ID
        assert success.obj['planned'] is True
        assert success.changes == OVERWRITE_DIFF
        assert success.overwritten is True

    def test_both_types_are_guarded_as_an_update(self) -> None:
        """The stored object's type and the type the row is written as must both be active"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID, OTHER_TYPE_ID)])
        other_type = _target_type()
        importer.objects_manager.get_object_type.return_value = other_type

        _run(importer, [_id_row(OVERWRITTEN_ID)])

        guarded = [(call.args[0], call.args[3], call.args[4], call.args[5])
                   for call in importer.objects_manager.guard_writable_type.call_args_list]
        assert guarded == [
            (OTHER_TYPE_ID, ObjectsManagerUpdateError, ObjectWriteVerb.UPDATED.value, other_type),
            (TARGET_TYPE_ID, ObjectsManagerUpdateError, ObjectWriteVerb.UPDATED.value, importer.target_type),
        ]

    def test_the_same_type_is_guarded_once(self) -> None:
        """An object overwritten with its own type costs one guard"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)])

        _run(importer, [_id_row(OVERWRITTEN_ID)])

        importer.objects_manager.guard_writable_type.assert_called_once()

    def test_a_deactivated_type_refuses_the_overwrite_as_itself(self) -> None:
        """The guard's refusal is the row's failure, named as it is; nothing is written"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)])
        importer.objects_manager.guard_writable_type.side_effect = AccessDeniedError('deactivated')
        overwriter = _Overwriter()

        result = _run(importer, [_id_row(OVERWRITTEN_ID)], overwriter=overwriter)

        assert result.failed_imports[0].errors == ['deactivated']
        assert not overwriter.replaced

    def test_an_object_gone_before_the_replace_is_imported_under_its_id(self) -> None:
        """Nothing matched the replace, so the row is written as a new object with that id - a CREATE"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)])
        row = _id_row(OVERWRITTEN_ID)

        result = _run(importer, [row], overwriter=_Overwriter(matched=False))

        success = result.success_imports[0]
        assert (success.public_id, success.overwritten) == (OVERWRITTEN_ID, False)
        assert importer.objects_manager.insert_object.call_args.args[0] is row[1]
        assert 'planned' not in row[1]

    def test_another_type_is_read_once_per_import(self) -> None:
        """Two overwritten objects of the same foreign type cost one type read"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID, OTHER_TYPE_ID),
                                     _stored(OVERWRITTEN_ID + 1, OTHER_TYPE_ID)])
        importer.objects_manager.get_object_type.return_value = _target_type()

        result = _run(importer, [_id_row(OVERWRITTEN_ID), _id_row(OVERWRITTEN_ID + 1)])

        assert result.failed_imports == []
        importer.objects_manager.get_object_type.assert_called_once_with(OTHER_TYPE_ID)

    def test_an_incompatible_existing_type_rejects_the_row(self) -> None:
        """A field the existing object's type lacks refuses the overwrite; nothing is deleted"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)])

        overwriter = _Overwriter()

        result = _run(importer, [_id_row(OVERWRITTEN_ID, [FIELD_A, FIELD_B])], overwriter=overwriter)

        assert result.failed_imports[0].errors == [
            f"Cannot overwrite object {OVERWRITTEN_ID}: its type does not support field(s) ['{FIELD_B}']",
        ]
        assert not overwriter.replaced

    def test_a_missing_existing_type_rejects_the_row(self) -> None:
        """Without the type there is nothing to check the fields against"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID, OTHER_TYPE_ID)])
        importer.objects_manager.get_object_type.return_value = None

        result = _run(importer, [_id_row(OVERWRITTEN_ID)])

        assert result.failed_imports[0].errors == [
            f'Cannot overwrite object {OVERWRITTEN_ID}: its type (ID:{OTHER_TYPE_ID}) does not exist',
        ]

    def test_a_file_naming_an_id_twice_overwrites_its_own_first_row(self) -> None:
        """The second row finds the first row's object, as when every row read the database itself"""
        importer = _importer()
        first, second = _id_row(OVERWRITTEN_ID), _id_row(OVERWRITTEN_ID)
        overwriter = _Overwriter()

        result = _run(importer, [first, second], overwriter=overwriter)

        assert [message.overwritten for message in result.success_imports] == [False, True]
        assert overwriter.planned == [(first[1], second[1])]

    def test_a_file_naming_an_id_three_times_overwrites_the_replacement(self) -> None:
        """The third row finds what the second row wrote, not the first row's object"""
        importer = _importer()
        rows = [_id_row(OVERWRITTEN_ID), _id_row(OVERWRITTEN_ID), _id_row(OVERWRITTEN_ID)]
        overwriter = _Overwriter()

        _run(importer, rows, overwriter=overwriter)

        assert overwriter.planned[1][0] == {**rows[1][1], 'planned': True}

    def test_a_failed_read_fails_every_row_with_an_id(self) -> None:
        """Without the stored objects no row can be judged; the new rows are written regardless"""
        importer = _importer()
        importer.objects_manager.find_objects.side_effect = ObjectsManagerGetError('db down')

        result = _run(importer, [_id_row(OVERWRITTEN_ID), _new_row()])

        assert [message.errors for message in result.failed_imports] == [['db down']]
        assert len(result.success_imports) == 1

    @pytest.mark.parametrize('error', [
        ObjectsManagerUpdateError('write failed'),
        DocumentNetworkError('Network/timeout error'),
    ], ids=['refused', 'lost connection'])
    def test_a_failed_replace_fails_the_row_as_itself(self, error: Exception) -> None:
        """A refused or interrupted replace is the row's failure, named as it is; nothing else is written"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)])

        result = _run(importer, [_id_row(OVERWRITTEN_ID)], overwriter=_Overwriter(error=error))

        assert result.failed_imports[0].errors == [str(error)]
        importer.objects_manager.insert_object.assert_not_called()

    def test_an_unplannable_overwrite_fails_the_row(self) -> None:
        """A stored object the model cannot read is refused before anything is written"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)])
        overwriter = _Overwriter()

        with patch(f'{PATH}.current_app') as current_app, \
                patch(f'{PATH}.normalize_and_validate_object', return_value=[]), \
                patch(f'{PATH}.plan_overwrite', side_effect=ObjectsManagerUpdateError('unreadable')), \
                patch(f'{PATH}.replace_stored_object', side_effect=overwriter.replace), \
                patch(f'{PATH}.handle_sync_config_item_count'):
            current_app.cloud_mode = False
            result = importer._import([_id_row(OVERWRITTEN_ID)], None)

        assert result.failed_imports[0].errors == ['unreadable']
        assert not overwriter.replaced

    def test_a_lost_connection_on_an_insert_is_reported_as_itself(self) -> None:
        """A transient failure is the database's answer, not an unexpected bug"""
        importer = _importer()
        importer.objects_manager.insert_object.side_effect = DocumentNetworkError('Network/timeout error')

        result = _run(importer, [_id_row(OVERWRITTEN_ID)])

        assert result.failed_imports[0].errors == ['Network/timeout error']

    def test_the_id_the_insert_answers_is_reported(self) -> None:
        """A supplied id that clashed is stored under a drawn one - the report names where it went"""
        importer = _importer()
        importer.objects_manager.insert_object.side_effect = lambda document, **_kwargs: NEW_OBJECT_FIRST_ID

        result = _run(importer, [_id_row(OVERWRITTEN_ID)])

        assert result.success_imports[0].public_id == NEW_OBJECT_FIRST_ID

    def test_an_unexpected_error_fails_only_that_row(self) -> None:
        """The per-object safety net holds for the rows with an id too"""
        importer = _importer()
        importer.objects_manager.insert_object.side_effect = [RuntimeError('boom'), OVERWRITTEN_ID + 1]

        result = _run(importer, [_id_row(OVERWRITTEN_ID), _id_row(OVERWRITTEN_ID + 1)])

        assert result.failed_imports[0].errors == ['Unexpected error while importing this object: boom']
        assert [message.public_id for message in result.success_imports] == [OVERWRITTEN_ID + 1]


class TestNewRows:
    """The rows without a public_id: one guard, then one reservation and one insert per chunk."""

    def test_the_new_rows_go_in_one_write(self) -> None:
        """Three rows, one call of the batched writer, one guard of the target type"""
        importer = _importer()
        writer = _Writer()

        _run(importer, [_new_row(), _new_row(), _new_row()], writer)

        assert len(writer.calls) == 1 and len(writer.calls[0]) == 3
        importer.objects_manager.guard_writable_type.assert_called_once()
        importer.objects_manager.get_object_type.assert_not_called()

    def test_the_new_rows_are_written_in_chunks(self) -> None:
        """A chunk size of two splits three rows into two writes"""
        writer = _Writer()

        with patch(f'{PATH}.IMPORT_INSERT_CHUNK_SIZE', CHUNK_OF_TWO):
            result = _run(_importer(), [_new_row(), _new_row(), _new_row()], writer)

        assert [len(call) for call in writer.calls] == [CHUNK_OF_TWO, 1]
        assert len(result.success_imports) == 3

    def test_a_deactivated_type_fails_every_new_row(self) -> None:
        """The guard's refusal is each row's failure, named as it is"""
        importer = _importer()
        importer.objects_manager.guard_writable_type.side_effect = AccessDeniedError('deactivated')
        writer = _Writer()

        result = _run(importer, [_new_row(), _new_row()], writer)

        assert [message.errors for message in result.failed_imports] == [['deactivated'], ['deactivated']]
        assert not writer.calls

    def test_a_refused_object_fails_on_its_own(self) -> None:
        """The others of the chunk are written; the refused one is reported with its error"""
        writer = _Writer(failures={1: DocumentInsertError('refused')})

        result = _run(_importer(), [_new_row('a'), _new_row('b'), _new_row('c')], writer)

        assert [message.failed_object for message in result.failed_imports] == [{'name': 'b'}]
        assert result.failed_imports[0].errors == ['refused']
        assert [message.public_id for message in result.success_imports] == [NEW_OBJECT_FIRST_ID,
                                                                             NEW_OBJECT_FIRST_ID + 2]

    def test_a_public_id_clash_is_retried_with_a_drawn_id(self) -> None:
        """The taken id is replaced by a freshly drawn one and the object is written on its own"""
        importer = _importer()
        clash = DocumentInsertDuplicateKeyError('dup', key_pattern={'public_id': 1}, key_value={'public_id': 1})
        importer.objects_manager.get_new_object_public_id.return_value = RETRIED_ID

        result = _run(importer, [_new_row()], _Writer(failures={0: clash}))

        assert result.success_imports[0].public_id == RETRIED_ID
        retried: dict = importer.objects_manager.insert_object.call_args.args[0]
        assert retried['public_id'] == RETRIED_ID
        assert importer.objects_manager.insert_object.call_args.kwargs == {
            'id_from_counter': True, 'object_type': importer.target_type,
        }

    def test_a_failed_draw_fails_the_row(self) -> None:
        """Without a fresh id there is nothing to retry with"""
        importer = _importer()
        clash = DocumentInsertDuplicateKeyError('dup', key_pattern={'public_id': 1})
        importer.objects_manager.get_new_object_public_id.side_effect = ObjectsManagerGetError('no counter')

        result = _run(importer, [_new_row()], _Writer(failures={0: clash}))

        assert result.failed_imports[0].errors == ['no counter']
        importer.objects_manager.insert_object.assert_not_called()

    def test_another_duplicate_is_not_retried(self) -> None:
        """A clash on another index is the document's own, so a fresh id would not help"""
        importer = _importer()
        clash = DocumentInsertDuplicateKeyError('dup', key_pattern={'name': 1}, key_value={'name': 'x'})

        result = _run(importer, [_new_row()], _Writer(failures={0: clash}))

        assert result.failed_imports[0].errors == ['dup']
        importer.objects_manager.insert_object.assert_not_called()

    def test_a_failed_retry_fails_the_row(self) -> None:
        """The retry is the last attempt"""
        importer = _importer()
        clash = DocumentInsertDuplicateKeyError('dup', key_pattern={'public_id': 1})
        importer.objects_manager.insert_object.side_effect = ObjectsManagerInsertError('again')

        result = _run(importer, [_new_row()], _Writer(failures={0: clash}))

        assert result.failed_imports[0].errors == ['again']

    def test_a_chunk_that_failed_as_a_whole_is_read_back(self) -> None:
        """What was stored before the failure counts as imported; the rest fails with the chunk's error"""
        importer = _importer()
        importer.objects_manager.find_objects.return_value = [{'public_id': NEW_OBJECT_FIRST_ID}]

        result = _run(importer, [_new_row('a'), _new_row('b')], _Writer(error=BaseManagerInsertError('lost')))

        assert [message.public_id for message in result.success_imports] == [NEW_OBJECT_FIRST_ID]
        assert result.failed_imports[0].errors == ['lost']
        importer.objects_manager.find_objects.assert_called_once_with(
            {'public_id': {'$in': [NEW_OBJECT_FIRST_ID, NEW_OBJECT_FIRST_ID + 1]}}, as_dict=True,
            projection={'public_id': 1},
        )

    def test_a_failed_read_back_fails_the_whole_chunk(self) -> None:
        """Without the read nothing can be confirmed"""
        importer = _importer()
        importer.objects_manager.find_objects.side_effect = ObjectsManagerGetError('db down')

        result = _run(importer, [_new_row(), _new_row()], _Writer(error=BaseManagerInsertError('lost')))

        assert [message.errors for message in result.failed_imports] == [['lost'], ['lost']]

    def test_a_failed_reservation_is_not_read_back(self) -> None:
        """No id was handed out, so nothing can have been written"""
        importer = _importer()

        def _no_ids(_manager: object, _documents: list[dict]) -> dict:
            raise BaseManagerGetError('no counter')

        with patch(f'{PATH}.current_app') as current_app, \
                patch(f'{PATH}.normalize_and_validate_object', return_value=[]), \
                patch(f'{PATH}.insert_new_objects', side_effect=_no_ids), \
                patch(f'{PATH}.handle_sync_config_item_count'):
            current_app.cloud_mode = False
            result = importer._import([_new_row()], None)

        assert result.failed_imports[0].errors == ['no counter']
        importer.objects_manager.find_objects.assert_not_called()

    def test_an_unexpected_chunk_error_is_reported_as_one(self) -> None:
        """A bug in the write is named as unexpected, not as a refusal"""
        result = _run(_importer(), [_new_row()], _Writer(error=KeyError('bug')))

        assert result.failed_imports[0].errors == ["Unexpected error while importing this object: 'bug'"]


class TestProvidedFieldNames:
    """_provided_field_names collects the field names the file provided (top-level + MDS)."""

    def test_collects_top_level_and_mds_names(self) -> None:
        """Top-level field names and MDS-row field names are both collected."""
        obj = {
            'fields': [{'name': 'a'}, {'name': 'b'}],
            'multi_data_sections': [{'section_id': 's', 'values': [{'data': [{'name': 'c'}]}]}],
        }

        assert ObjectImporter._provided_field_names(obj) == {'a', 'b', 'c'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   _import_for_type                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImportForType:
    """_import_for_type derives the normalization context from the type and delegates to _import."""

    def test_derives_context_and_delegates(self) -> None:
        """It passes the type's special_type and the derived ImportTypeContext to _import."""
        mock_self = MagicMock()
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [
            {'name': 'owner', 'type': 'ref', 'required': True},   # ref -> exempt from required
            {'name': 'host', 'type': 'text', 'required': True},
            {'name': 'note', 'type': 'text'},
        ]
        type_instance.get_sections.return_value = []
        type_instance.special_type = 'SUBNET'
        mock_self._import.return_value = 'RESULT'
        mock_self._resolve_predefined_select_fields.return_value = {}

        result = ObjectImporter._import_for_type(mock_self, ['cand'], type_instance)

        expected_context = ImportTypeContext(
            clearable_reference_fields={'owner'},
            field_type_map={'owner': 'ref', 'host': 'text', 'note': 'text'},
            required_top_level={'host'},
            required_mds_by_section={},
            top_level_field_defaults={'owner': None, 'host': None, 'note': None},
            mds_field_defaults_by_section={},
            field_options={},
            predefined_select_fields={},
            new_select_options={},
            field_value_rules={
                'host': FieldValueRule(max_length=TEXT_VALUE_MAX_LENGTH),
                'note': FieldValueRule(max_length=TEXT_VALUE_MAX_LENGTH),
            },
        )
        mock_self._resolve_predefined_select_fields.assert_called_once_with(type_instance)
        mock_self._import.assert_called_once_with(['cand'], 'SUBNET', expected_context)
        assert result == 'RESULT'

    def test_persists_new_select_options_when_the_import_records_them(self) -> None:
        """When the batch records new select options, _import_for_type delegates to the persist step."""
        mock_self = MagicMock()
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [{'name': 'kind', 'type': 'select'}]
        type_instance.get_sections.return_value = []
        type_instance.special_type = None
        # simulate _import filling the context's new_select_options during the batch
        mock_self._import.side_effect = lambda candidates, special_type, ctx: ctx.new_select_options.update(
            {'kind': ['x']}) or 'RESULT'

        result = ObjectImporter._import_for_type(mock_self, ['cand'], type_instance)

        assert result == 'RESULT'
        mock_self._persist_new_select_options.assert_called_once_with(type_instance, {'kind': ['x']})

    def test_predefined_select_fields_are_carried_into_the_context(self) -> None:
        """The resolved predefined-template select fields become part of the normalization context."""
        mock_self = MagicMock()
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [{'name': 'dg-interface-type', 'type': 'select'}]
        type_instance.get_sections.return_value = []
        type_instance.special_type = None
        mock_self._resolve_predefined_select_fields.return_value = {'dg-interface-type': 'dg-ipam-interface'}

        ObjectImporter._import_for_type(mock_self, ['cand'], type_instance)

        passed_context = mock_self._import.call_args.args[2]
        assert passed_context.predefined_select_fields == {'dg-interface-type': 'dg-ipam-interface'}

    def test_resolve_predefined_select_fields_delegates_to_the_guard(self) -> None:
        """_resolve_predefined_select_fields builds a SectionTemplatesManager and asks the guard."""
        mock_self = MagicMock()
        mock_self.objects_manager.dbm = 'DBM'
        mock_self.objects_manager.db_name = 'DB'
        type_instance = MagicMock()

        with patch(f'{PATH}.SectionTemplatesManager') as manager_cls, \
             patch(f'{PATH}.resolve_predefined_select_fields', return_value={'a': 't'}) as resolver:
            result = ObjectImporter._resolve_predefined_select_fields(mock_self, type_instance)

        manager_cls.assert_called_once_with('DBM', 'DB')
        resolver.assert_called_once_with(type_instance, manager_cls.return_value)
        assert result == {'a': 't'}

    def test_persist_new_select_options_applies_and_updates_the_type(self) -> None:
        """_persist_new_select_options adds the options to the type and saves it once via TypesManager."""
        mock_self = MagicMock()
        field = {'name': 'kind', 'type': 'select', 'options': [{'name': 'a', 'label': 'a'}]}
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [field]
        type_instance.public_id = 5

        with patch(f'{PATH}.TypesManager') as types_manager_cls:
            ObjectImporter._persist_new_select_options(mock_self, type_instance, {'kind': ['b']})

        assert {'name': 'b', 'label': 'b'} in field['options']
        types_manager_cls.return_value.update_type.assert_called_once_with(5, type_instance)


class TestAbstractMethods:
    """generate_object and start_import must be implemented by concrete importers."""

    def test_generate_object_is_abstract(self) -> None:
        """The base generate_object raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            ObjectImporter.generate_object(MagicMock(), {})

    def test_start_import_is_abstract(self) -> None:
        """The base start_import raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            ObjectImporter.start_import(MagicMock())


class TestConfigItemLimit:
    """The import asks the user's own limit rule, against a count it reads once per import"""

    def test_the_check_asks_the_users_rule(self) -> None:
        """At the limit the check reports True, below it False - the same answer the object route gets"""
        at_limit = _importer(stored_count=LIMIT)
        below_limit = _importer(stored_count=LIMIT - 1)

        assert at_limit.check_config_item_limit_reached(at_limit.request_user) is True
        assert below_limit.check_config_item_limit_reached(below_limit.request_user) is False

    def test_a_limit_of_zero_refuses_the_first_row(self) -> None:
        """0 is a literal limit on the import too - the object route and the import refuse alike"""
        writer = _Writer()

        result = _run(_importer(limit=0), [_new_row()], writer, cloud_mode=True)

        assert result.failed_imports[0].errors == [CONFIG_ITEM_LIMIT_REACHED_MESSAGE]
        assert not writer.calls

    def test_a_missing_limit_gets_the_default_instead_of_a_type_error(self) -> None:
        """A null limit reaches the check as the default, so the comparison never meets a None"""
        result = _run(_importer(limit=None), [_new_row()], cloud_mode=True)

        assert len(result.success_imports) == 1

    def test_the_count_is_read_once_per_import(self) -> None:
        """Three rows, one count_documents - the import keeps the number current itself"""
        importer = _importer()

        _run(importer, [_new_row(), _id_row(OVERWRITTEN_ID), _new_row()], cloud_mode=True)

        importer.objects_manager.count_documents.assert_called_once_with()

    def test_the_rows_of_the_import_use_up_the_budget(self) -> None:
        """With two free slots the first two rows are written and the third is refused"""
        writer = _Writer()

        result = _run(_importer(stored_count=LIMIT - FREE_SLOTS), [_new_row('a'), _new_row('b'), _new_row('c')],
                      writer, cloud_mode=True)

        assert [document['fields'][0]['value'] for document in writer.calls[0]] == ['a', 'b']
        assert [message.failed_object for message in result.failed_imports] == [{'name': 'c'}]

    def test_a_row_with_an_id_takes_its_slot_first(self) -> None:
        """The rows with an id are written first, so they are counted first"""
        writer = _Writer()

        result = _run(_importer(stored_count=LIMIT - 1), [_new_row('a'), _id_row(OVERWRITTEN_ID)], writer,
                      cloud_mode=True)

        assert [message.public_id for message in result.success_imports] == [OVERWRITTEN_ID]
        assert result.failed_imports[0].errors == [CONFIG_ITEM_LIMIT_REACHED_MESSAGE]

    def test_a_row_with_an_unused_id_at_the_limit_is_refused(self) -> None:
        """An unused id adds an object, so it needs a slot like a new row"""
        importer = _importer(stored_count=LIMIT)

        result = _run(importer, [_id_row(OVERWRITTEN_ID)], cloud_mode=True)

        assert result.failed_imports[0].errors == [CONFIG_ITEM_LIMIT_REACHED_MESSAGE]
        importer.objects_manager.insert_object.assert_not_called()

    @pytest.mark.parametrize('stored_count', [LIMIT, LIMIT + 1], ids=['at the limit', 'above the limit'])
    def test_an_overwrite_is_never_refused_by_the_limit(self, stored_count: int) -> None:
        """An overwrite adds no object: it goes through even above the limit and leaves the count as it was"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)], stored_count=stored_count)
        importer._stored_object_count()

        result = _run(importer, [_id_row(OVERWRITTEN_ID)], cloud_mode=True)

        assert result.failed_imports == []
        assert importer._object_count == stored_count

    def test_an_overwrite_does_not_count_the_stored_objects(self) -> None:
        """The limit is not asked, so an import of overwrites alone costs no count"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)])

        _run(importer, [_id_row(OVERWRITTEN_ID)], cloud_mode=True)

        importer.objects_manager.count_documents.assert_not_called()

    def test_an_object_gone_before_the_replace_needs_a_slot(self) -> None:
        """Imported under its id as a new object, it adds one - refused at the limit"""
        importer = _importer(stored=[_stored(OVERWRITTEN_ID)], stored_count=LIMIT)

        result = _run(importer, [_id_row(OVERWRITTEN_ID)], cloud_mode=True, overwriter=_Overwriter(matched=False))

        assert result.failed_imports[0].errors == [CONFIG_ITEM_LIMIT_REACHED_MESSAGE]
        importer.objects_manager.insert_object.assert_not_called()

    def test_a_failed_insert_gives_its_slot_back(self) -> None:
        """A row the database refused is not counted as stored"""
        importer = _importer(stored_count=0)

        _run(importer, [_new_row(), _new_row()], _Writer(failures={0: DocumentInsertError('refused')}),
             cloud_mode=True)

        assert importer._object_count == 1

    def test_a_write_before_the_first_count_is_not_tracked(self) -> None:
        """Outside cloud mode nothing counts; the first real count then reads the database afresh"""
        importer = _importer(stored_count=FREE_SLOTS)

        _run(importer, [_new_row(), _id_row(OVERWRITTEN_ID)])

        assert importer._object_count is None
        assert importer._stored_object_count() == FREE_SLOTS


# -------------------------------------------------------------------------------------------------------------------- #
#                                              resolve_target_type                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

class TestResolveTargetType:
    """The target Type is resolved once - the route usually hands it over already."""

    def test_a_handed_over_type_is_returned_without_a_read(self) -> None:
        """The route resolved and authorised it, so reading it again would be a wasted query."""
        mock_self = MagicMock()
        mock_self.target_type = 'THE TYPE'

        assert ObjectImporter.resolve_target_type(mock_self) == 'THE TYPE'
        mock_self.objects_manager.get_object_type.assert_not_called()

    def test_it_falls_back_to_reading_the_type(self) -> None:
        """A caller that built the importer itself still gets a resolved type."""
        mock_self = MagicMock()
        mock_self.target_type = None
        mock_self.get_config.return_value.get_type_id.return_value = 42

        result = ObjectImporter.resolve_target_type(mock_self)

        assert result is mock_self.objects_manager.get_object_type.return_value
        mock_self.objects_manager.get_object_type.assert_called_once_with(42)

    def test_the_fallback_read_happens_once(self) -> None:
        """The read result is remembered, so a second call costs nothing."""
        mock_self = MagicMock()
        mock_self.target_type = None
        mock_self.get_config.return_value.get_type_id.return_value = 42

        first = ObjectImporter.resolve_target_type(mock_self)
        mock_self.target_type = first
        second = ObjectImporter.resolve_target_type(mock_self)

        assert first is second
        mock_self.objects_manager.get_object_type.assert_called_once()
