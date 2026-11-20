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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Functional tests: the object import's overwrite keeps the user sync's lock

Through ``POST /import/object/`` with overwrite on: a row that changes a synced person's synced value fails and leaves
the stored person - its link included - as it was; a row carrying the same synced values and a new phone number
overwrites it and keeps the link
"""
import json
from http import HTTPStatus
from io import BytesIO
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
# -------------------------------------------------------------------------------------------------------------------- #

IMPORT_URL: str = '/import/object/'
PERSON_TYPE_ID: int = 9541
SYNCED_PERSON_ID: int = 9542
USER_ID: int = 9543
AUTHOR_ID: int = 1
LOCKED_MESSAGE: str = 'change only when the user changes'
SYSTEM_REF: dict[str, Any] = {'kind': 'user', 'id': USER_ID}
COLUMNS: list[str] = [PersonField.DISPLAY_NAME.value, PersonField.FIRST_NAME.value, PersonField.LAST_NAME.value,
                      PersonField.PHONE_NUMBER.value, PersonField.EMAIL.value]
STORED_VALUES: dict[str, str] = {
    PersonField.DISPLAY_NAME.value: 'Ann Lee', PersonField.FIRST_NAME.value: 'Ann',
    PersonField.LAST_NAME.value: 'Lee', PersonField.PHONE_NUMBER.value: '', PersonField.EMAIL.value: '',
}


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A PERSON Type and a synced person in it; removed afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    type_document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, 'fn-sync-lock-import',
                                                              PERSON_TYPE_ID)
    type_document['system_type'] = False
    types.insert_one(type_document)
    objects.insert_one({
        'public_id': SYNCED_PERSON_ID, 'type_id': PERSON_TYPE_ID, 'active': True, 'author_id': AUTHOR_ID,
        'version': '1.0.0', 'special_type': SpecialType.PERSON.value, 'multi_data_sections': [],
        'system_ref': SYSTEM_REF, 'sync_hash': 'stored-fingerprint',
        'fields': [{'name': name, 'value': value, 'type': 'text'} for name, value in STORED_VALUES.items()],
    })

    yield

    types.delete_one({'public_id': PERSON_TYPE_ID})
    objects.delete_many({'public_id': SYNCED_PERSON_ID})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': SYNCED_PERSON_ID})


def _import(rest_api, values: dict[str, str]) -> dict[str, Any]:
    """Imports one CSV row over the synced person, overwrite on, and answers the report"""
    header: str = ','.join(['public_id', *COLUMNS])
    row: str = ','.join([str(SYNCED_PERSON_ID), *(values[name] for name in COLUMNS)])
    mapping: list[dict[str, Any]] = [{'name': 'public_id', 'value': 0, 'type': 'property'}] + [
        {'name': name, 'value': index, 'type': 'field'} for index, name in enumerate(COLUMNS, start=1)
    ]
    config: dict[str, Any] = {'type_id': PERSON_TYPE_ID, 'overwrite_public': True, 'mapping': mapping}
    response = rest_api.post(IMPORT_URL, content_type='multipart/form-data', data={
        'file': (BytesIO(f'{header}\n{row}\n'.encode()), 'import.csv'), 'file_format': 'csv',
        'parser_config': json.dumps({}), 'importer_config': json.dumps(config),
    })

    assert response.status_code == HTTPStatus.OK
    return response.get_json()


def _stored(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """The stored person without its _id"""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
        {'public_id': SYNCED_PERSON_ID}, {'_id': 0})


def test_a_row_changing_a_synced_value_fails(rest_api, database_manager: MongoDatabaseManager,
                                             database_name: str) -> None:
    """The row fails naming the lock; the person and its link are as they were"""
    before = _stored(database_manager, database_name)

    report = _import(rest_api, {**STORED_VALUES, PersonField.FIRST_NAME.value: 'Anna'})

    assert report['success_imports'] == 0
    assert LOCKED_MESSAGE in report['failed_imports'][0]['errors'][0]
    assert _stored(database_manager, database_name) == before


def test_a_row_keeping_the_synced_values_overwrites(rest_api, database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
    """The person's own phone number changes; the link and the fingerprint stay"""
    report = _import(rest_api, {**STORED_VALUES, PersonField.PHONE_NUMBER.value: '555-0100'})

    assert report['success_imports'] == 1
    stored = _stored(database_manager, database_name)
    values = {entry['name']: entry['value'] for entry in stored['fields']}
    assert values[PersonField.PHONE_NUMBER.value] == '555-0100'
    assert (stored['system_ref'], stored['sync_hash']) == (SYSTEM_REF, 'stored-fingerprint')
