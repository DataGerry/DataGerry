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
Functional tests: what an object import writes, and how many round trips it costs, counted at the driver

Every created object gets its CREATE log, every overwritten one its EDIT log. The new objects are written with one id
reservation and one insert per chunk, their logs with one reservation and one insert for the whole import, and the
target type is read a fixed number of times - so the cost of an import of new rows does not grow with its rows. An
overwrite reads the stored objects once for all rows and replaces each with one replace - no delete, no insert. A
reserved id that is already taken (a counter left below a stored id) is written under a freshly drawn id instead
"""
import json
from collections import Counter
from http import HTTPStatus
from io import BytesIO
from typing import Any, Iterator

import pymongo.collection
import pytest

import cmdb.framework.importer.importers.object_importer as object_importer
from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

IMPORT_URL: str = '/import/object/'
TYPE_ID: int = 47391
NAME_FIELD: str = 'dg-name'
FEW_ROWS: int = 1
MANY_ROWS: int = 5
FIRST_OVERWRITTEN_ID: int = 47400
IMPORTED_COMMENT: str = 'Object was imported'
CHUNK_OF_TWO: int = 2
PUBLIC_ID_INDEX: str = 'public_id'
#: A new-row import: one reservation for the objects (one chunk) and one for their logs
NEW_ROW_RESERVATIONS: int = 2
DRIVER_OPERATIONS: list[str] = ['find', 'aggregate', 'insert_one', 'insert_many', 'update_one', 'find_one_and_update',
                                'delete_one', 'replace_one']


@pytest.fixture(autouse=True)
def _seed_type(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The target type; every imported object and its logs are removed afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_one(make_type_doc(TYPE_ID, 'import-writes'))
    yield

    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    imported_ids: list[int] = [document['public_id'] for document in objects.find({'type_id': TYPE_ID})]
    types.delete_one({'public_id': TYPE_ID})
    objects.delete_many({'type_id': TYPE_ID})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': imported_ids}})


@pytest.fixture(name='ops')
def fixture_ops(monkeypatch: pytest.MonkeyPatch) -> Counter:
    """Counts every driver operation, as '<collection>:<operation>'"""
    counted: Counter = Counter()

    for operation in DRIVER_OPERATIONS:
        original = getattr(pymongo.collection.Collection, operation)

        def _counting(collection: Any, *args: Any, _original: Any = original, _operation: str = operation,
                      **kwargs: Any) -> Any:
            counted[f'{collection.name}:{_operation}'] += 1
            return _original(collection, *args, **kwargs)

        monkeypatch.setattr(pymongo.collection.Collection, operation, _counting)

    return counted


def _form(body: bytes, overwrite: bool = False) -> dict[str, Any]:
    """The multipart import form; with overwrite, the first column is the public_id"""
    config: dict[str, Any] = {'type_id': TYPE_ID}

    if overwrite:
        config.update({'overwrite_public': True, 'mapping': [
            {'name': 'public_id', 'value': 0, 'type': 'property'},
            {'name': NAME_FIELD, 'value': 1, 'type': 'field'},
        ]})

    return {'file': (BytesIO(body), 'import.csv'), 'file_format': 'csv', 'parser_config': json.dumps({}),
            'importer_config': json.dumps(config)}


def _import_new(rest_api, rows: int) -> dict[str, Any]:
    """Imports ``rows`` new objects and answers the report"""
    body: bytes = f'{NAME_FIELD}\n'.encode() + b''.join(f'host-{row}\n'.encode() for row in range(rows))
    response = rest_api.post(IMPORT_URL, data=_form(body), content_type='multipart/form-data')

    assert response.status_code == HTTPStatus.OK
    return response.get_json()


def _import_overwrite(rest_api, database_manager: MongoDatabaseManager, database_name: str,
                      ops: Counter, rows: int) -> dict[str, Any]:
    """Seeds ``rows`` objects, then imports a file overwriting each; the counting starts with the import"""
    public_ids: list[int] = list(range(FIRST_OVERWRITTEN_ID, FIRST_OVERWRITTEN_ID + rows))
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many(
        [make_object_doc(public_id, TYPE_ID, [make_field(NAME_FIELD, 'old')]) for public_id in public_ids])
    ops.clear()
    body: bytes = f'public_id,{NAME_FIELD}\n'.encode() + b''.join(f'{i},new\n'.encode() for i in public_ids)

    response = rest_api.post(IMPORT_URL, data=_form(body, overwrite=True), content_type='multipart/form-data')

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['failed_imports'] == []
    return response.get_json()


def _logs_of(database_manager: MongoDatabaseManager, database_name: str) -> list[dict[str, Any]]:
    """The change logs of the imported objects"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    imported_ids: list[int] = [document['public_id'] for document in objects.find({'type_id': TYPE_ID})]

    return list(database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).find(
        {'object_id': {'$in': imported_ids}}))


#: The collections an import reads and writes - the request's own reads (the caller, the settings cache) are left out
IMPORT_COLLECTIONS: tuple[str, ...] = (
    CmdbObject.COLLECTION, CmdbType.COLLECTION, CmdbMetaLog.COLLECTION, PUBLIC_ID_COUNTER_COLLECTION,
)


def _per_import(ops: Counter) -> dict[str, int]:
    """The counts on the import's own collections"""
    return {key: count for key, count in ops.items() if key.split(':')[0] in IMPORT_COLLECTIONS}


class TestTheImportLogsEveryObject:
    """Each imported object gets its log - CREATE or EDIT - labelled as an import and stamped with its type."""

    def test_new_objects_are_logged(self, rest_api, database_manager: MongoDatabaseManager,
                                    database_name: str) -> None:
        """One entry per object, none lost"""
        report = _import_new(rest_api, MANY_ROWS)

        logs = _logs_of(database_manager, database_name)
        assert report['success_imports'] == MANY_ROWS
        assert len(logs) == MANY_ROWS
        assert {(log['comment'], log['type_id'], log['action_name']) for log in logs} == {
            (IMPORTED_COMMENT, TYPE_ID, 'CREATE')}

    def test_overwritten_objects_are_logged(self, rest_api, database_manager: MongoDatabaseManager,
                                            database_name: str, ops: Counter) -> None:
        """The overwrite path writes its entries too - as edits"""
        _import_overwrite(rest_api, database_manager, database_name, ops, MANY_ROWS)

        logs: list[dict[str, Any]] = _logs_of(database_manager, database_name)
        assert len(logs) == MANY_ROWS
        assert {(log['comment'], log['type_id'], log['action_name']) for log in logs} == {
            (IMPORTED_COMMENT, TYPE_ID, 'EDIT')}


class TestRoundTrips:
    """What an import costs at the driver."""

    def test_new_rows_cost_the_same_for_one_row_and_for_many(self, rest_api, ops: Counter) -> None:
        """The objects and their logs each take one reservation and one insert; the type is read a fixed number"""
        _import_new(rest_api, FEW_ROWS)
        few: dict[str, int] = _per_import(ops)
        ops.clear()

        _import_new(rest_api, MANY_ROWS)

        assert _per_import(ops) == few
        assert ops[f'{PUBLIC_ID_COUNTER_COLLECTION}:find_one_and_update'] == NEW_ROW_RESERVATIONS
        assert (ops[f'{CmdbObject.COLLECTION}:insert_many'], ops[f'{CmdbObject.COLLECTION}:insert_one']) == (1, 0)
        assert (ops[f'{CmdbMetaLog.COLLECTION}:insert_many'], ops[f'{CmdbMetaLog.COLLECTION}:insert_one']) == (1, 0)

    def test_the_new_rows_are_written_in_chunks(self, rest_api, ops: Counter, monkeypatch: pytest.MonkeyPatch) -> None:
        """A chunk size of two: three rows, two reservations and two inserts for the objects"""
        monkeypatch.setattr(object_importer, 'IMPORT_INSERT_CHUNK_SIZE', CHUNK_OF_TWO)

        report = _import_new(rest_api, CHUNK_OF_TWO + 1)

        assert report['success_imports'] == CHUNK_OF_TWO + 1
        assert ops[f'{CmdbObject.COLLECTION}:insert_many'] == 2

    def test_an_overwrite_reads_the_stored_objects_once(self, rest_api, database_manager: MongoDatabaseManager,
                                                        database_name: str, ops: Counter) -> None:
        """One read for every row's stored object and one to render the logs, however many rows; no type read
        grows with the rows; one replace per row and no delete or insert"""
        _import_overwrite(rest_api, database_manager, database_name, ops, FEW_ROWS)
        few_type_reads: int = ops[f'{CmdbType.COLLECTION}:find']

        _import_overwrite(rest_api, database_manager, database_name, ops, MANY_ROWS)

        assert ops[f'{CmdbObject.COLLECTION}:find'] == 2
        assert ops[f'{CmdbType.COLLECTION}:find'] == few_type_reads
        assert ops[f'{CmdbObject.COLLECTION}:replace_one'] == MANY_ROWS
        assert ops[f'{CmdbObject.COLLECTION}:delete_one'] == 0
        assert ops[f'{CmdbObject.COLLECTION}:insert_one'] == 0
        assert ops[f'{CmdbMetaLog.COLLECTION}:insert_many'] == 1


@pytest.fixture(name='unique_object_ids')
def fixture_unique_object_ids(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The unique public_id index a production database carries (the test session creates no indexes)"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    created: bool = PUBLIC_ID_INDEX not in objects.index_information()

    if created:
        objects.create_index('public_id', name=PUBLIC_ID_INDEX, unique=True)
    yield
    if created:
        objects.drop_index(PUBLIC_ID_INDEX)


@pytest.mark.usefixtures('unique_object_ids')
def test_a_taken_reserved_id_is_replaced_by_a_drawn_one(rest_api, database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
    """A counter left below a stored id: the row is still imported, under the next free id"""
    # The next id the counter would hand out - peeked, not drawn
    taken: int = database_manager.get_next_public_id(CmdbObject.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.insert_one(make_object_doc(taken, TYPE_ID, [make_field(NAME_FIELD, 'squatter')]))

    report = _import_new(rest_api, FEW_ROWS)

    assert report['failed_imports'] == []
    imported: list[dict[str, Any]] = list(objects.find({'type_id': TYPE_ID, 'public_id': {'$ne': taken}}))
    assert len(imported) == 1 and imported[0]['public_id'] > taken
    assert objects.count_documents({'public_id': taken}) == 1
