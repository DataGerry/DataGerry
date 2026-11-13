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
Functional tests for the person selector in the object export and import

Seeds a person type, a group type and an owning type whose ``owner`` (one person) and ``members`` (several persons and
groups) selectors hold them. Pinned:

  - a CSV export writes the ids, several joined by commas; a human-readable one writes the labels; JSON keeps the
    stored value
  - the CSV the export wrote imports back to the same selections
  - an import naming an object that does not exist, or one of a kind the selector does not select, is reported per
    row and not stored
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from io import BytesIO
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_selector.person_selector_constants import PersonSelectorWriteError
# -------------------------------------------------------------------------------------------------------------------- #

EXPORT_URL: str = '/export/object/'
IMPORT_URL: str = '/import/object/'

PERSON_TYPE: int = 48501
GROUP_TYPE: int = 48502
OWNING_TYPE: int = 48503
TYPE_IDS: list[int] = [PERSON_TYPE, GROUP_TYPE, OWNING_TYPE]

ADA: int = 48511
BOB: int = 48512
OPS: int = 48513
HOLDER: int = 48521
SEEDED_OBJECT_IDS: list[int] = [ADA, BOB, OPS, HOLDER]

OWNER: str = 'owner'
MEMBERS: str = 'members'


def _type(public_id: int, name: str, marker: str = '', fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A type document; a person or group type labels by its base field"""
    fields = fields or [{'type': 'text', 'name': 'display_name' if marker == 'PERSON' else 'name', 'label': 'Label'}]

    return {
        'public_id': public_id, 'name': name, 'label': name.title(), 'author_id': 1, 'active': True,
        'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'special_type': marker, 'fields': fields,
        'render_meta': {'icon': 'fa-cube', 'summary': {'fields': []}, 'sections': [
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [field['name'] for field in fields]},
        ]},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object(public_id: int, type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """An object document"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': fields}


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The types, the persons and the holder; everything of these types removed before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def _purge() -> None:
        imported: list[int] = [document['public_id'] for document in objects.find({'type_id': OWNING_TYPE})]
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'type_id': {'$in': TYPE_IDS}})
        logs.delete_many({'object_id': {'$in': imported}})

    _purge()
    selectors: list[dict[str, Any]] = [
        {'type': 'person', 'name': OWNER, 'label': 'Owner', 'selectable': ['PERSON'], 'multiple': False},
        {'type': 'person', 'name': MEMBERS, 'label': 'Members', 'selectable': ['PERSON', 'PERSON_GROUP'],
         'multiple': True},
    ]
    types.insert_many([_type(PERSON_TYPE, 'xfer-person', 'PERSON'), _type(GROUP_TYPE, 'xfer-group', 'PERSON_GROUP'),
                       _type(OWNING_TYPE, 'xfer-owning', fields=selectors)])
    objects.insert_many([
        _object(ADA, PERSON_TYPE, [{'name': 'display_name', 'type': 'text', 'value': 'Ada'}]),
        _object(BOB, PERSON_TYPE, [{'name': 'display_name', 'type': 'text', 'value': 'Bob'}]),
        _object(OPS, GROUP_TYPE, [{'name': 'name', 'type': 'text', 'value': 'Ops'}]),
        _object(HOLDER, OWNING_TYPE, [{'name': OWNER, 'type': 'person', 'value': ADA},
                                      {'name': MEMBERS, 'type': 'person', 'value': [BOB, OPS]}]),
    ])
    yield objects
    _purge()


def _export(rest_api: Any, export_format: str, **params: str) -> Any:
    """Exports the owning type's objects"""
    response = rest_api.get(EXPORT_URL, query_string={
        'filter': json.dumps({'type_id': OWNING_TYPE}), 'classname': export_format, **params,
    })
    assert response.status_code == HTTPStatus.OK

    return response


def _csv_rows(response: Any) -> list[str]:
    """The lines of a CSV export"""
    return response.get_data(as_text=True).strip().splitlines()


def _import(rest_api: Any, body: str, owner_column: int, members_column: int) -> Any:
    """Imports a CSV into the owning type, the two selectors mapped by column index"""
    mapping: list[dict[str, Any]] = [{'name': OWNER, 'value': owner_column, 'type': 'field'},
                                     {'name': MEMBERS, 'value': members_column, 'type': 'field'}]
    form = {'file': (BytesIO(body.encode('utf-8')), 'import.csv'), 'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({'type_id': OWNING_TYPE, 'mapping': mapping})}

    return rest_api.post(IMPORT_URL, data=form, content_type='multipart/form-data')


def _imported(objects: Any) -> list[dict[str, Any]]:
    """The selector values of every imported object"""
    return [{entry['name']: entry['value'] for entry in document['fields']}
            for document in objects.find({'type_id': OWNING_TYPE, 'public_id': {'$ne': HOLDER}})]


@pytest.mark.usefixtures('seeded')
def test_a_csv_export_writes_the_ids(rest_api) -> None:
    """Several joined by commas, quoted as one cell"""
    header, row = _csv_rows(_export(rest_api, 'CsvExportFormat'))

    assert header == 'public_id,active,owner,members'
    assert row == f'{HOLDER},True,{ADA},"{BOB},{OPS}"'


@pytest.mark.usefixtures('seeded')
def test_a_human_readable_export_writes_the_labels(rest_api) -> None:
    """Presentation only"""
    _, row = _csv_rows(_export(rest_api, 'CsvExportFormat', human_readable='true'))

    assert row.endswith('Ada,"Bob, Ops"')


@pytest.mark.usefixtures('seeded')
def test_a_json_export_keeps_the_stored_value(rest_api) -> None:
    """A list stays a list"""
    (exported,) = json.loads(_export(rest_api, 'JsonExportFormat').get_data(as_text=True))
    values = {field['name']: field['value'] for field in exported['fields']}

    assert values == {OWNER: ADA, MEMBERS: [BOB, OPS]}


def test_the_exported_csv_imports_back(rest_api, seeded) -> None:
    """The same selections, on a new object"""
    header, row = _csv_rows(_export(rest_api, 'CsvExportFormat'))
    body: str = f'{header}\n{row.replace(str(HOLDER), "", 1)}\n'

    response = _import(rest_api, body, owner_column=2, members_column=3)

    assert response.status_code == HTTPStatus.OK, response.get_json()
    assert _imported(seeded) == [{OWNER: ADA, MEMBERS: [BOB, OPS]}]


@pytest.mark.parametrize('owner, members, message', [
    (str(ADA), '999999', PersonSelectorWriteError.UNKNOWN.format(name=MEMBERS, ids=[999999])),
    (str(OPS), '', PersonSelectorWriteError.NOT_SELECTABLE.format(name=OWNER, kinds=['PERSON'], ids=[OPS])),
], ids=['unknown', 'group-in-person-selector'])
def test_a_refused_selection_is_reported_and_not_stored(rest_api, seeded, owner: str, members: str,
                                                        message: str) -> None:
    """Per row, like every other import refusal"""
    response = _import(rest_api, f'owner,members\n{owner},"{members}"\n', owner_column=0, members_column=1)

    errors: list[str] = [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]
    assert errors == [message]
    assert _imported(seeded) == []
