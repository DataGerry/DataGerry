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
Functional tests: an object import that overwrites a stored object, through ``POST /import/object/``

An overwrite is one atomic replace of the stored object under its public_id. Pinned over HTTP against a real
MongoDB: a write the database refuses, or a connection lost during it, fails the row and leaves the stored object
exactly as it was; the cloud ConfigItem limit never refuses an overwrite, even above the limit; the object's
risk assessments survive; an object deleted between the import's read and its write is still imported under its
id; a file naming an id twice overwrites its own first row; a deactivated type refuses the overwrite as itself;
and the overwrite is recorded as an edit - stored author and creation time kept, the version bumped, an EDIT log
carrying the diff
"""
import json
from http import HTTPStatus
from io import BytesIO
from types import SimpleNamespace
from typing import Any, Iterator

import pymongo.collection
import pytest
from pymongo.errors import AutoReconnect, OperationFailure

import cmdb.framework.importer.importers.object_importer as object_importer
from cmdb.database import MongoDatabaseManager
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_group_model import ObjectReferenceType
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.importer.importer_constants import UNEXPECTED_OBJECT_IMPORT_ERROR
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

IMPORT_URL: str = '/import/object/'
TYPE_ID: int = 14261
DEACTIVATED_TYPE_ID: int = 14262
OVERWRITTEN_ID: int = 14271
UNUSED_ID: int = 14272
RISK_ASSESSMENT_ID: int = 14281
ADMIN_ID: int = 1
STORED_AUTHOR_ID: int = 14291
STORED_VERSION: str = '3.1.4'
BUMPED_VERSION: str = '3.1.5'
NAME_FIELD: str = 'dg-name'
STORED_VALUE: str = 'stored'
IMPORTED_VALUE: str = 'imported'
IMPORTED_COMMENT: str = 'Object was imported'
DEACTIVATED_TYPE_NAME: str = 'import-overwrite-deactivated'
DEACTIVATED_MESSAGE: str = f'Objects cannot be updated because type `{DEACTIVATED_TYPE_NAME}` is deactivated.'
REFUSED_CODE: int = 2


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The target type and the object the import overwrites; everything written is removed afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.insert_one(make_type_doc(TYPE_ID, 'import-overwrite'))
    stored: dict[str, Any] = make_object_doc(OVERWRITTEN_ID, TYPE_ID, [make_field(NAME_FIELD, STORED_VALUE)])
    stored.update(author_id=STORED_AUTHOR_ID, version=STORED_VERSION)
    objects.insert_one(stored)
    yield

    types.delete_many({'public_id': {'$in': [TYPE_ID, DEACTIVATED_TYPE_ID]}})
    objects.delete_many({'$or': [{'type_id': TYPE_ID}, {'public_id': {'$in': [OVERWRITTEN_ID, UNUSED_ID]}}]})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': [OVERWRITTEN_ID, UNUSED_ID]}})


def _stored(database_manager: MongoDatabaseManager, database_name: str, public_id: int = OVERWRITTEN_ID) -> Any:
    """The object stored under the id, as the database holds it"""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': public_id})


def _logs(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> list[dict[str, Any]]:
    """The change logs of one object, oldest first"""
    return list(database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).find(
        {'object_id': public_id}).sort('public_id', 1))


def _import(rest_api, rows: list[tuple[int, str]]) -> dict[str, Any]:
    """Imports a CSV whose rows are (public_id, name) with overwrite on, and answers the report"""
    body: bytes = f'public_id,{NAME_FIELD}\n'.encode() + b''.join(f'{i},{name}\n'.encode() for i, name in rows)
    config: dict[str, Any] = {'type_id': TYPE_ID, 'overwrite_public': True, 'mapping': [
        {'name': 'public_id', 'value': 0, 'type': 'property'},
        {'name': NAME_FIELD, 'value': 1, 'type': 'field'},
    ]}
    response = rest_api.post(IMPORT_URL, content_type='multipart/form-data', data={
        'file': (BytesIO(body), 'import.csv'), 'file_format': 'csv', 'parser_config': json.dumps({}),
        'importer_config': json.dumps(config),
    })

    assert response.status_code == HTTPStatus.OK
    return response.get_json()


def _fail_object_replaces(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """Makes every replace of a stored object fail with ``error``; other collections are untouched"""
    original = pymongo.collection.Collection.replace_one

    def _failing(collection: Any, *args: Any, **kwargs: Any) -> Any:
        if collection.name == CmdbObject.COLLECTION:
            raise error
        return original(collection, *args, **kwargs)

    monkeypatch.setattr(pymongo.collection.Collection, 'replace_one', _failing)


class TestAFailedWriteLosesNothing:
    """The stored object survives every failure of the overwrite's write."""

    def test_a_refused_write_leaves_the_stored_object(self, rest_api, database_manager: MongoDatabaseManager,
                                                      database_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """The row fails, the object is exactly as it was, and nothing was logged"""
        before: dict[str, Any] = _stored(database_manager, database_name)
        _fail_object_replaces(monkeypatch, OperationFailure('write refused', code=REFUSED_CODE))

        report = _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

        assert report['success_imports'] == 0
        assert 'write refused' in report['failed_imports'][0]['errors'][0]
        assert _stored(database_manager, database_name) == before
        assert not _logs(database_manager, database_name, OVERWRITTEN_ID)

    def test_a_lost_connection_leaves_the_stored_object(self, rest_api, database_manager: MongoDatabaseManager,
                                                        database_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reported as the database's answer, not as an unexpected error; the object is untouched"""
        before: dict[str, Any] = _stored(database_manager, database_name)
        _fail_object_replaces(monkeypatch, AutoReconnect('connection lost'))

        report = _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

        error: str = report['failed_imports'][0]['errors'][0]
        assert 'connection lost' in error
        assert not error.startswith(UNEXPECTED_OBJECT_IMPORT_ERROR.format(detail=''))
        assert _stored(database_manager, database_name) == before


class TestTheOverwriteIsAnEdit:
    """The stored object is replaced in place and the change is recorded as an edit."""

    def test_the_object_is_replaced_in_place(self, rest_api, database_manager: MongoDatabaseManager,
                                             database_name: str) -> None:
        """Same _id, the imported value, the object count unchanged"""
        before: dict[str, Any] = _stored(database_manager, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        count_before: int = objects.count_documents({})

        report = _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

        after: dict[str, Any] = _stored(database_manager, database_name)
        assert report['success_imports'] == 1
        assert after['_id'] == before['_id']
        assert after['fields'][0]['value'] == IMPORTED_VALUE
        assert objects.count_documents({}) == count_before

    def test_the_stored_authorship_is_kept_and_the_version_bumped(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Created by whom it was, edited by the importer, one version up"""
        _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

        after: dict[str, Any] = _stored(database_manager, database_name)
        assert (after['author_id'], after['editor_id']) == (STORED_AUTHOR_ID, ADMIN_ID)
        assert after['version'] == BUMPED_VERSION
        assert after['last_edit_time'] is not None

    def test_the_overwrite_is_logged_as_an_edit_with_its_diff(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """One EDIT entry, labelled as an import, carrying the old and the new value and the bumped version"""
        _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

        logs: list[dict[str, Any]] = _logs(database_manager, database_name, OVERWRITTEN_ID)
        assert [(log['action_name'], log['comment'], log['version']) for log in logs] == [
            ('EDIT', IMPORTED_COMMENT, BUMPED_VERSION)]
        assert logs[0]['changes'] == {'old': [make_field(NAME_FIELD, STORED_VALUE)],
                                      'new': [{**make_field(NAME_FIELD, IMPORTED_VALUE), 'type': 'text'}]}

    def test_the_risk_assessments_survive(self, rest_api, database_manager: MongoDatabaseManager,
                                          database_name: str) -> None:
        """Nothing is deleted, so nothing is cascaded"""
        risk_assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        risk_assessments.insert_one({'public_id': RISK_ASSESSMENT_ID, 'object_id': OVERWRITTEN_ID,
                                     'object_id_ref_type': ObjectReferenceType.OBJECT.value})

        try:
            report = _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

            assert report['success_imports'] == 1
            assert risk_assessments.count_documents({'public_id': RISK_ASSESSMENT_ID}) == 1
        finally:
            risk_assessments.delete_one({'public_id': RISK_ASSESSMENT_ID})

    def test_a_deactivated_stored_type_refuses_the_overwrite_as_itself(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The stored object's own type is deactivated: the refusal names it; the object is untouched"""
        deactivated: dict[str, Any] = make_type_doc(DEACTIVATED_TYPE_ID, DEACTIVATED_TYPE_NAME)
        deactivated['active'] = False
        database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(deactivated)
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
            {'public_id': OVERWRITTEN_ID}, {'$set': {'type_id': DEACTIVATED_TYPE_ID}})
        before: dict[str, Any] = _stored(database_manager, database_name)

        report = _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

        assert report['failed_imports'][0]['errors'] == [DEACTIVATED_MESSAGE]
        assert _stored(database_manager, database_name) == before


class TestRowsThatAddAnObject:
    """A row whose id holds no object (any more) is a new object."""

    def test_an_object_deleted_before_the_write_is_imported_under_its_id(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
            monkeypatch: pytest.MonkeyPatch) -> None:
        """Deleted after the import read it: the row is still written, as a new object with a CREATE log"""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        real_plan = object_importer.plan_overwrite

        def _deleted_meanwhile(*args: Any) -> Any:
            objects.delete_one({'public_id': OVERWRITTEN_ID})
            return real_plan(*args)

        monkeypatch.setattr(object_importer, 'plan_overwrite', _deleted_meanwhile)

        report = _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

        after: dict[str, Any] = _stored(database_manager, database_name)
        assert report['success_imports'] == 1
        assert (after['fields'][0]['value'], after['author_id'], after['version']) == (IMPORTED_VALUE, ADMIN_ID,
                                                                                        '1.0.0')
        assert [log['action_name'] for log in _logs(database_manager, database_name, OVERWRITTEN_ID)] == ['CREATE']

    def test_a_file_naming_an_id_twice_overwrites_its_own_first_row(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The first row creates the object, the second edits it - one object, a CREATE then an EDIT"""
        report = _import(rest_api, [(UNUSED_ID, 'first'), (UNUSED_ID, 'second')])

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        assert report['success_imports'] == 2
        assert objects.count_documents({'public_id': UNUSED_ID}) == 1
        assert _stored(database_manager, database_name, UNUSED_ID)['fields'][0]['value'] == 'second'
        assert [log['action_name'] for log in _logs(database_manager, database_name, UNUSED_ID)] == [
            'CREATE', 'EDIT']


@pytest.fixture(name='cloud_limit_zero')
def fixture_cloud_limit_zero(database_manager: MongoDatabaseManager, database_name: str,
                             monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The importer runs in cloud mode and the importing admin's ConfigItem limit is 0 - every tenant is above it"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    previous: Any = users.find_one({'public_id': ADMIN_ID}).get('config_items_limit')
    users.update_one({'public_id': ADMIN_ID}, {'$set': {'config_items_limit': 0}})
    monkeypatch.setattr(object_importer, 'current_app', SimpleNamespace(cloud_mode=True))
    monkeypatch.setattr(object_importer, 'handle_sync_config_item_count', lambda _user: None)
    yield
    users.update_one({'public_id': ADMIN_ID}, {'$set': {'config_items_limit': previous}})


@pytest.mark.usefixtures('cloud_limit_zero')
class TestTheConfigItemLimit:
    """An overwrite adds no object, so the limit never refuses it."""

    def test_an_overwrite_above_the_limit_goes_through(self, rest_api, database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
        """The object is replaced and the count stays the same"""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        count_before: int = objects.count_documents({})

        report = _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE)])

        assert report['failed_imports'] == []
        assert _stored(database_manager, database_name)['fields'][0]['value'] == IMPORTED_VALUE
        assert objects.count_documents({}) == count_before

    def test_a_row_adding_an_object_above_the_limit_is_still_refused(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The same file's unused id needs a slot; the overwrite beside it goes through"""
        report = _import(rest_api, [(OVERWRITTEN_ID, IMPORTED_VALUE), (UNUSED_ID, IMPORTED_VALUE)])

        assert report['success_imports'] == 1
        assert report['failed_imports'][0]['errors'] == ['Config item limit reached!']
        assert _stored(database_manager, database_name, UNUSED_ID) is None
