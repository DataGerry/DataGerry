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
Unit tests for cmdb.framework.importer.helper.object_import_writer

DB-free: the ObjectsManager is a mock, the documents are real CmdbObject documents. Pinned for the new objects:
the ids come from one reservation and land on the documents in order; an object the model cannot hold fails on
its own without reaching the insert; the insert's refusals are mapped back from the positions of the documents
sent to the positions of the chunk; a failed reservation writes nothing. Pinned for an overwrite: the stored
author and creation time are kept, the importer is stamped as the editor, the version is bumped by what changed
and kept when nothing did, the diff is answered and neither argument is changed; the replace sends the stored
form under the public_id, answers whether anything matched, and reports a refused or unholdable write as an
update error while a transient one passes through. The real replace is in
``tests/integration/framework/test_integration_object_import_overwrite.py``
"""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.importer.helper.object_import_writer import (
    insert_new_objects,
    plan_overwrite,
    replace_stored_object,
    serialise_new_objects,
)
from cmdb.models.user_model import CmdbUser
from cmdb.errors.database import DocumentInsertError, DocumentNetworkError, DocumentUpdateError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.objects_manager import ObjectsManagerInsertError, ObjectsManagerUpdateError
from tests.utils.ipam_doc_builders import make_object_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9
FIRST_RESERVED_ID: int = 300
OVERWRITTEN_ID: int = 7
OTHER_TYPE_ID: int = 11
STORED_AUTHOR_ID: int = 3
IMPORTER_ID: int = 5
STORED_VERSION: str = '2.3.4'
BUMPED_VERSION: str = '2.3.5'
STORED_CREATION_TIME: datetime = datetime(2024, 1, 2, tzinfo=timezone.utc)


def _new_object() -> dict[str, Any]:
    """A normalised new object, without its public_id"""
    document = make_object_doc(0, TYPE_ID, [])
    document.pop('public_id')

    return document


def _unholdable() -> dict[str, Any]:
    """An object the model refuses (it names no type)"""
    document = _new_object()
    document.pop('type_id')

    return document


def _manager(amount: int, refusals: dict[int, Exception] | None = None) -> MagicMock:
    """An ObjectsManager that reserves ``amount`` ids and refuses the given positions of what it is sent"""
    manager = MagicMock()
    manager.reserve_public_ids.return_value = list(range(FIRST_RESERVED_ID, FIRST_RESERVED_ID + amount))
    manager.insert_many_reporting.return_value = refusals or {}

    return manager


class TestSerialiseNewObjects:
    """The stored form of each object, built one at a time."""

    def test_every_holdable_object_is_serialised_with_its_position(self) -> None:
        """An unholdable object in the middle shifts nothing: positions name the input"""
        documents = [_new_object(), _unholdable(), _new_object()]
        for public_id, document in enumerate(documents, start=1):
            document['public_id'] = public_id

        serialised, positions, failures = serialise_new_objects(documents)

        assert [document['public_id'] for document in serialised] == [1, 3]
        assert positions == [0, 2]
        assert list(failures) == [1] and isinstance(failures[1], ObjectsManagerInsertError)


class TestInsertNewObjects:
    """One reservation, one insert, each refusal at its own position."""

    def test_the_ids_come_from_one_reservation_in_order(self) -> None:
        """Written into the documents, so the caller reports them"""
        documents = [_new_object(), _new_object()]
        manager = _manager(2)

        assert insert_new_objects(manager, documents) == {}

        manager.reserve_public_ids.assert_called_once_with(2)
        assert [document['public_id'] for document in documents] == [FIRST_RESERVED_ID, FIRST_RESERVED_ID + 1]
        sent, = manager.insert_many_reporting.call_args.args
        assert [document['public_id'] for document in sent] == [FIRST_RESERVED_ID, FIRST_RESERVED_ID + 1]

    def test_a_refusal_is_mapped_back_past_an_unholdable_object(self) -> None:
        """The insert answers positions of what it was sent; the caller gets positions of its chunk"""
        refusal = DocumentInsertError('refused')
        manager = _manager(3, {1: refusal})

        failures = insert_new_objects(manager, [_unholdable(), _new_object(), _new_object()])

        assert sorted(failures) == [0, 2]
        assert failures[2] is refusal
        assert len(manager.insert_many_reporting.call_args.args[0]) == 2

    def test_a_failed_reservation_writes_nothing(self) -> None:
        """No id, no insert - the error reaches the caller"""
        manager = MagicMock()
        manager.reserve_public_ids.side_effect = BaseManagerGetError('no counter')
        documents = [_new_object()]

        with pytest.raises(BaseManagerGetError):
            insert_new_objects(manager, documents)

        manager.insert_many_reporting.assert_not_called()
        assert 'public_id' not in documents[0]


def _stored_object() -> dict[str, Any]:
    """The stored object an overwrite replaces: its own author, creation time and version"""
    document = make_object_doc(OVERWRITTEN_ID, TYPE_ID, [{'name': 'a', 'value': 'stored'},
                                                         {'name': 'b', 'value': 'kept'}])
    document.update(author_id=STORED_AUTHOR_ID, creation_time=STORED_CREATION_TIME, version=STORED_VERSION)

    return document


def _imported_object(value: str = 'imported') -> dict[str, Any]:
    """The normalised imported row: authored by the importer, fresh version, another type"""
    document = make_object_doc(OVERWRITTEN_ID, OTHER_TYPE_ID, [{'name': 'a', 'value': value},
                                                               {'name': 'b', 'value': 'kept'}])
    document['author_id'] = IMPORTER_ID

    return document


def _importer() -> CmdbUser:
    """The user running the import"""
    return CmdbUser(public_id=IMPORTER_ID, user_name='importer', active=True)


class TestPlanOverwrite:
    """An overwrite is an edit of the stored object."""

    def test_the_stored_authorship_is_kept(self) -> None:
        """Who created the object and when survive the overwrite"""
        replacement, _changes = plan_overwrite(_stored_object(), _imported_object(), _importer())

        assert replacement['author_id'] == STORED_AUTHOR_ID
        assert replacement['creation_time'] == STORED_CREATION_TIME

    def test_the_importer_is_stamped_as_the_editor(self) -> None:
        """The edit stamp names the importer and now"""
        before: datetime = datetime.now(timezone.utc)

        replacement, _changes = plan_overwrite(_stored_object(), _imported_object(), _importer())

        assert replacement['editor_id'] == IMPORTER_ID
        assert replacement['last_edit_time'] >= before

    def test_everything_else_is_the_imported_row(self) -> None:
        """The type and the field values are the row's"""
        replacement, _changes = plan_overwrite(_stored_object(), _imported_object(), _importer())

        assert replacement['type_id'] == OTHER_TYPE_ID
        assert replacement['fields'] == _imported_object()['fields']

    def test_a_changed_value_bumps_the_stored_version(self) -> None:
        """The bump starts from the stored version, not the row's fresh one"""
        replacement, _changes = plan_overwrite(_stored_object(), _imported_object(), _importer())

        assert replacement['version'] == BUMPED_VERSION

    def test_an_unchanged_object_keeps_its_version(self) -> None:
        """Nothing changed, nothing to bump"""
        replacement, changes = plan_overwrite(_stored_object(), _imported_object('stored'), _importer())

        assert replacement['version'] == STORED_VERSION
        assert changes == {'old': [], 'new': []}

    def test_the_diff_names_the_changed_field(self) -> None:
        """Old and new value of the one field that changed - what the EDIT log records"""
        _replacement, changes = plan_overwrite(_stored_object(), _imported_object(), _importer())

        assert changes == {'old': [{'name': 'a', 'value': 'stored'}], 'new': [{'name': 'a', 'value': 'imported'}]}

    def test_neither_argument_is_changed(self) -> None:
        """The import keeps reporting the row as it was; the stored object stays what was read"""
        stored, imported = _stored_object(), _imported_object()
        stored_before, imported_before = copy.deepcopy(stored), copy.deepcopy(imported)

        plan_overwrite(stored, imported, _importer())

        assert (stored, imported) == (stored_before, imported_before)

    def test_an_unreadable_stored_object_is_an_update_error(self) -> None:
        """A stored object the model cannot read is refused before anything is written"""
        stored = _stored_object()
        stored.pop('type_id')

        with pytest.raises(ObjectsManagerUpdateError):
            plan_overwrite(stored, _imported_object(), _importer())


class TestReplaceStoredObject:
    """One replace under the public_id."""

    @staticmethod
    def _manager(matched_count: int = 1) -> MagicMock:
        """An ObjectsManager whose replace matched ``matched_count`` documents"""
        manager = MagicMock()
        manager.replace.return_value = SimpleNamespace(matched_count=matched_count)

        return manager

    def test_the_stored_form_is_sent_under_the_public_id(self) -> None:
        """What insert_object would store, sent as one replace"""
        manager = self._manager()
        document = _imported_object()

        assert replace_stored_object(manager, document) is True

        public_id, sent = manager.replace.call_args.args
        assert public_id == OVERWRITTEN_ID
        assert (sent['public_id'], sent['type_id'], sent['author_id']) == (OVERWRITTEN_ID, OTHER_TYPE_ID, IMPORTER_ID)
        assert sent['fields'] == document['fields']

    def test_nothing_matched_is_answered_false(self) -> None:
        """The object was deleted after the import read it - the caller decides what follows"""
        assert replace_stored_object(self._manager(matched_count=0), _imported_object()) is False

    def test_a_refused_write_is_an_update_error_carrying_the_refusal(self) -> None:
        """The manager's error is wrapped as itself, not as its text"""
        manager = MagicMock()
        refusal = BaseManagerUpdateError(DocumentUpdateError('write failed'))
        manager.replace.side_effect = refusal

        with pytest.raises(ObjectsManagerUpdateError) as raised:
            replace_stored_object(manager, _imported_object())

        assert raised.value.args[0] is refusal

    def test_an_unholdable_object_is_refused_before_the_write(self) -> None:
        """The model's refusal never reaches the database"""
        manager = self._manager()
        document = _imported_object()
        document.pop('type_id')

        with pytest.raises(ObjectsManagerUpdateError):
            replace_stored_object(manager, document)

        manager.replace.assert_not_called()

    def test_a_transient_failure_passes_through(self) -> None:
        """A lost connection stays what it is, so the import reports it as such"""
        manager = MagicMock()
        manager.replace.side_effect = DocumentNetworkError('Network/timeout error')

        with pytest.raises(DocumentNetworkError):
            replace_stored_object(manager, _imported_object())
