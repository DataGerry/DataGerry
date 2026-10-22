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
What an object's multi-data sections look like after an export and an import - end to end, through the routes

`GET /exporter/` writes the seeded object, it is deleted, and `POST /import/object/` creates it again from the file.
Pinned for each format: what a reader of the file sees of an MDS field, and what the re-imported object stores.

* JSON is the round trip of the stored object: `fields` keeps each MDS field's flat entry next to its rows, and the
  import stores both as written
* CSV writes an MDS field once, per row: the rows come back; the flat MDS entries do not - as on an object the
  create route makes, the backend never adds them (the renderer fills them in on read)
* XML writes an MDS field in its rows only; it has no importer
"""
import json
import xml.etree.ElementTree as ET
from http import HTTPStatus
from io import BytesIO
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from tests.utils import mds_export_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

EXPORT_URL: str = '/exporter/'
IMPORT_URL: str = '/import/object/'
IDENTITY_COLUMNS: tuple[str, ...] = ('public_id', 'active')


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the MDS type and object; removes them, whatever an import created, and its logs after"""
    seed.seed(database_manager, database_name)
    yield
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    created: list[int] = [doc['public_id'] for doc in objects.find({'type_id': seed.TYPE_ID})]
    seed.purge(database_manager, database_name)
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many({'object_id': {'$in': created}})


def _export(rest_api, classname: str) -> bytes:
    """The real export of the seeded type"""
    response = rest_api.get(EXPORT_URL, query_string={'filter': json.dumps({'type_id': seed.TYPE_ID}),
                                                      'classname': classname})
    assert response.status_code == HTTPStatus.OK

    return response.data


def _reimport(rest_api, database_manager: MongoDatabaseManager, database_name: str, body: bytes, file_format: str,
              importer_config: dict[str, Any]) -> dict[str, Any]:
    """Deletes the seeded object, imports the file and answers the one object it created"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'type_id': seed.TYPE_ID})

    response = rest_api.post(IMPORT_URL, data={
        'file': (BytesIO(body), f'objects.{file_format}'), 'file_format': file_format,
        'parser_config': json.dumps({}),
        'importer_config': json.dumps({'type_id': seed.TYPE_ID, **importer_config}),
    }, content_type='multipart/form-data')

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['failed_imports'] == []
    stored: list[dict[str, Any]] = list(objects.find({'type_id': seed.TYPE_ID}))
    assert len(stored) == 1

    return stored[0]


def _flat(stored: dict[str, Any]) -> list[tuple[str, Any]]:
    """The stored flat field entries as (name, value)"""
    return [(field['name'], field.get('value')) for field in stored['fields']]


def _rows(stored: dict[str, Any]) -> list[list[tuple[str, Any]]]:
    """The stored MDS rows as (name, value) pairs"""
    return [[(entry['name'], entry['value']) for entry in row['data']]
            for section in stored.get('multi_data_sections', []) for row in section['values']]


class TestJson:
    """The round trip of the stored object."""

    def test_the_flat_entries_and_the_rows_come_back(self, rest_api, database_manager, database_name) -> None:
        """Both exactly as stored - the flat MDS entries included, with their own values"""
        stored = _reimport(rest_api, database_manager, database_name, _export(rest_api, 'JsonExportFormat'),
                           'json', {})

        assert _flat(stored) == [(field['name'], field['value']) for field in seed.stored_flat_fields()]
        assert _rows(stored) == seed.stored_rows()


class TestCsv:
    """An MDS field once, per row."""

    def test_the_rows_come_back_and_no_flat_mds_entry_is_stored(
            self, rest_api, database_manager, database_name) -> None:
        """The regular field and the rows as exported; the flat MDS entries absent, as on a created object"""
        body: bytes = _export(rest_api, 'CsvExportFormat')
        header: list[str] = body.decode('utf-8').splitlines()[0].split(',')
        mapping = [{'name': column, 'value': index,
                    'type': 'property' if column in IDENTITY_COLUMNS else 'field'}
                   for index, column in enumerate(header)]

        stored = _reimport(rest_api, database_manager, database_name, body, 'csv', {'mapping': mapping})

        assert _flat(stored) == [(seed.NAME_FIELD, seed.NAME_VALUE)]
        assert _rows(stored) == seed.stored_rows()


class TestXml:
    """No importer - what the reader sees."""

    def test_an_mds_field_is_in_its_rows_only(self, rest_api) -> None:
        """<fields> without it; the flat value nowhere in the file"""
        body: bytes = _export(rest_api, 'XmlExportFormat')
        obj = ET.fromstring(body).find('object')

        assert [field.attrib['name'] for field in obj.findall('fields/field')] == [seed.NAME_FIELD]
        assert seed.FLAT_PORT.encode() not in body and seed.FLAT_SPEED.encode() not in body
