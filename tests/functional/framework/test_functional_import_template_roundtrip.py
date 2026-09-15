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
Functional round trip of the object-import template

Downloads the template of a seeded type from `GET /exporter/template/<type_id>`, fills the real header
in with data and feeds it back through `POST /import/object/parse/` and `POST /import/object/`. This is
the end-to-end proof that the decorated header (`<Label> [MDS-<Section>] [<name>]`) is accepted by the
import: the parse preview answers resolved identifiers (plus the labels in `raw_header`), the regular
field imports through the index mapping, the multi-data-section entries are reassembled, and a
continuation row (blank public_id) is grouped into the same object instead of creating a second one.
"""
import json
from http import HTTPStatus
from io import BytesIO
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TEMPLATE_URL: str = '/exporter/template'
IMPORT_URL: str = '/import/object'

TYPE_ID: int = 47701

NAME_FIELD: str = 'dg-name'
MDS_PORT_FIELD: str = 'port'
MDS_SPEED_FIELD: str = 'speed'
MDS_SECTION_ID: str = 'ifaces'
MDS_SECTION_LABEL: str = 'Network Interfaces'

HOST_VALUE: str = 'host-1'
FIRST_PORT: str = '80'
SECOND_PORT: str = '443'

EXPECTED_IDENTIFIERS: list[str] = ['public_id', 'active', NAME_FIELD, MDS_PORT_FIELD, MDS_SPEED_FIELD]


@pytest.fixture(autouse=True)
def _seed_type(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a type with a regular field and a two-field multi-data-section; cleans up after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_one(make_type_doc(
        TYPE_ID,
        'import-template-type',
        fields=[
            {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
            {'type': 'text', 'name': MDS_PORT_FIELD, 'label': 'Port'},
            {'type': 'text', 'name': MDS_SPEED_FIELD, 'label': 'Speed'},
        ],
        sections=[
            {'type': 'section', 'name': 'information', 'label': 'Information', 'fields': [NAME_FIELD]},
            {'type': 'multi-data-section', 'name': MDS_SECTION_ID, 'label': MDS_SECTION_LABEL,
             'fields': [MDS_PORT_FIELD, MDS_SPEED_FIELD]},
        ],
    ))

    yield

    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    imported_ids = [doc['public_id'] for doc in objects.find({'type_id': TYPE_ID})]

    types.delete_many({'public_id': TYPE_ID})
    objects.delete_many({'type_id': TYPE_ID})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)\
        .delete_many({'object_id': {'$in': imported_ids}})


def _template_header(rest_api) -> str:
    """Downloads the type's import template and returns its header line."""
    response = rest_api.get(f'{TEMPLATE_URL}/{TYPE_ID}')

    assert response.status_code == HTTPStatus.OK

    return response.get_data(as_text=True).splitlines()[0]


def _filled_template(rest_api) -> bytes:
    """Fills the downloaded template with one object carrying two multi-data-section entries."""
    header = _template_header(rest_api)
    # A blank public_id continues the previous object - the flattened MDS layout the export uses
    rows = [
        f',true,{HOST_VALUE},{FIRST_PORT},1G',
        f',,,{SECOND_PORT},10G',
    ]

    return '\n'.join([header, *rows]).encode('utf-8')


def _mapping() -> list[dict[str, Any]]:
    """Maps the regular column by INDEX, as the frontend does for a CSV (index 2 = the name field)."""
    return [{'name': NAME_FIELD, 'value': 2, 'type': 'field'}]


def _import_form(rest_api) -> dict[str, Any]:
    """Builds the multipart import form carrying the filled-in template."""
    return {
        'file': (BytesIO(_filled_template(rest_api)), 'template.csv'),
        'file_format': 'csv',
        'parser_config': json.dumps({}),
        'importer_config': json.dumps({'type_id': TYPE_ID, 'mapping': _mapping()}),
    }


class TestTemplateParsePreview:
    """The parse preview resolves the template's decorated header without losing the labels."""

    def test_header_holds_the_resolved_identifiers(self, rest_api) -> None:
        """`header` carries plain field names - exactly what a client saw before templates existed."""
        form = {
            'file': (BytesIO(_filled_template(rest_api)), 'template.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{IMPORT_URL}/parse/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['header'] == EXPECTED_IDENTIFIERS

    def test_raw_header_keeps_the_template_labels(self, rest_api) -> None:
        """`raw_header` is the file's own line, so the labels stay available for display."""
        form = {
            'file': (BytesIO(_filled_template(rest_api)), 'template.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{IMPORT_URL}/parse/', data=form, content_type='multipart/form-data')

        raw_header = response.get_json()['raw_header']

        assert raw_header[0] == 'Public ID [public_id]'
        assert f'[MDS-{MDS_SECTION_LABEL}]' in raw_header[3]

    def test_a_plain_header_is_unaffected(self, rest_api) -> None:
        """An export-style file still parses to the same header it always did."""
        form = {
            'file': (BytesIO(b'public_id,active,dg-name\n,true,host-9\n'), 'plain.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
        }

        response = rest_api.post(f'{IMPORT_URL}/parse/', data=form, content_type='multipart/form-data')
        body = response.get_json()

        assert body['header'] == ['public_id', 'active', 'dg-name']
        assert body['raw_header'] == body['header']


class TestFilledTemplateImports:
    """A filled-in template imports as one object, multi-data-sections included."""

    def _import(self, rest_api):
        """Posts the filled template to the import route."""
        return rest_api.post(
            f'{IMPORT_URL}/', data=_import_form(rest_api), content_type='multipart/form-data',
        )

    def _imported(self, database_manager: MongoDatabaseManager, database_name: str) -> list[dict[str, Any]]:
        """Returns the objects the import created for the seeded type."""
        return list(
            database_manager.get_collection(CmdbObject.COLLECTION, database_name).find({'type_id': TYPE_ID})
        )

    def test_the_two_rows_become_one_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The continuation row is grouped in - the decorated public_id column is still recognised."""
        assert self._import(rest_api).status_code == HTTPStatus.OK

        assert len(self._imported(database_manager, database_name)) == 1

    def test_the_mapped_regular_field_is_stored(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The regular column imports through the index mapping, as before."""
        self._import(rest_api)

        stored = self._imported(database_manager, database_name)[0]
        values = {field['name']: field['value'] for field in stored['fields']}

        assert values[NAME_FIELD] == HOST_VALUE

    def test_the_multi_data_section_is_reassembled(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Both rows contribute an MDS entry - the columns are matched despite the decorated header."""
        self._import(rest_api)

        sections = self._imported(database_manager, database_name)[0]['multi_data_sections']

        assert len(sections) == 1
        assert sections[0]['section_id'] == MDS_SECTION_ID
        assert sections[0]['highest_id'] == 2

        ports = [
            entry['value']
            for row in sections[0]['values']
            for entry in row['data']
            if entry['name'] == MDS_PORT_FIELD
        ]

        assert ports == [int(FIRST_PORT), int(SECOND_PORT)]
