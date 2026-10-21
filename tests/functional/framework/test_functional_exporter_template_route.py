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
Functional coverage for `GET /exporter/template/<type_id>`

Pins the object-import template a user downloads: a CSV holding exactly one row - the self-describing
header - built from a seeded CmdbType with a regular section and a multi-data-section. Asserts the
column layout and order, the CSV content type and the download filename (timestamp, sanitised type
label, template marker), plus the guards: an unknown type is 404, a type without fields is 400, and an
unauthorized request never reaches either.
"""
import csv
from datetime import datetime, timezone
from http import HTTPStatus
from io import StringIO
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

TEMPLATE_URL: str = '/exporter/template'

TYPE_ID: int = 47601
TYPE_WITHOUT_FIELDS_ID: int = 47602
MISSING_TYPE_ID: int = 47699
ALL_TYPE_IDS: list[int] = [TYPE_ID, TYPE_WITHOUT_FIELDS_ID]

TYPE_LABEL: str = 'Template Type (Core)'
SANITISED_TYPE_LABEL: str = 'template-type-core'

NAME_FIELD: str = 'dg-name'
UNLABELLED_FIELD: str = 'notes'
MDS_PORT_FIELD: str = 'port'
MDS_SPEED_FIELD: str = 'speed'
MDS_SECTION_LABEL: str = 'Network Interfaces'

EXPECTED_HEADER: list[str] = [
    'Public ID [public_id]',
    'Active [active]',
    f'Name [{NAME_FIELD}]',
    f'{UNLABELLED_FIELD} [{UNLABELLED_FIELD}]',
    f'Port [MDS-{MDS_SECTION_LABEL}] [{MDS_PORT_FIELD}]',
    f'Speed [MDS-{MDS_SECTION_LABEL}] [{MDS_SPEED_FIELD}]',
]


def _type_doc(public_id: int, fields: list[dict[str, Any]], sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds an active CmdbType document for direct DB insertion."""
    return {
        'public_id': public_id,
        'name': f'template-type-{public_id}',
        'label': TYPE_LABEL,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': fields,
        'render_meta': {
            'icon': 'fa-cube',
            'sections': sections,
            'summary': {'fields': []},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one full type (regular + MDS section) and one without fields; removes both afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_many([
        _type_doc(
            TYPE_ID,
            [
                {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
                {'type': 'text', 'name': UNLABELLED_FIELD},
                {'type': 'text', 'name': MDS_PORT_FIELD, 'label': 'Port'},
                {'type': 'text', 'name': MDS_SPEED_FIELD, 'label': 'Speed'},
            ],
            [
                {'type': 'section', 'name': 'main', 'label': 'Main',
                 'fields': [NAME_FIELD, UNLABELLED_FIELD]},
                {'type': 'multi-data-section', 'name': 'ifaces', 'label': MDS_SECTION_LABEL,
                 'fields': [MDS_PORT_FIELD, MDS_SPEED_FIELD]},
            ],
        ),
        _type_doc(TYPE_WITHOUT_FIELDS_ID, [], []),
    ])

    yield

    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


def _rows(response) -> list[list[str]]:
    """Parses the response body as CSV."""
    return list(csv.reader(StringIO(response.get_data(as_text=True))))


class TestObjectImportTemplate:
    """The template of a seeded type: one header row, self-describing columns, CSV download."""

    def test_returns_only_the_header_row(self, rest_api) -> None:
        """A template carries no data - exactly one row, the header."""
        response = rest_api.get(f'{TEMPLATE_URL}/{TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        assert _rows(response) == [EXPECTED_HEADER]

    def test_columns_are_self_describing_and_mirror_an_export(self, rest_api) -> None:
        """Identity columns lead, regular fields follow in section order, MDS fields close the row."""
        header = _rows(rest_api.get(f'{TEMPLATE_URL}/{TYPE_ID}'))[0]

        assert header[:2] == ['Public ID [public_id]', 'Active [active]']
        assert all(column.endswith(']') for column in header)
        assert [column for column in header if 'MDS-' in column] == header[-2:]

    def test_an_unlabelled_field_falls_back_to_its_name(self, rest_api) -> None:
        """A field without a label is still readable rather than headed by brackets alone."""
        header = _rows(rest_api.get(f'{TEMPLATE_URL}/{TYPE_ID}'))[0]

        assert f'{UNLABELLED_FIELD} [{UNLABELLED_FIELD}]' in header

    def test_is_served_as_a_csv_download_named_after_the_type_label(self, rest_api) -> None:
        """The response is a CSV attachment whose name ends in the template marker."""
        response = rest_api.get(f'{TEMPLATE_URL}/{TYPE_ID}')

        assert response.mimetype == 'text/csv'
        disposition = response.headers['Content-Disposition']
        assert 'attachment;' in disposition
        assert f'{SANITISED_TYPE_LABEL}_template.csv"' in disposition

    def test_missing_type_returns_404(self, rest_api) -> None:
        """A template can only be built for a type that exists."""
        assert rest_api.get(f'{TEMPLATE_URL}/{MISSING_TYPE_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_type_without_fields_returns_400(self, rest_api) -> None:
        """A type declaring no field cannot be filled in, so the request is refused, not answered."""
        response = rest_api.get(f'{TEMPLATE_URL}/{TYPE_WITHOUT_FIELDS_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_unauthorized_request_is_rejected(self, rest_api) -> None:
        """Authentication runs before anything is read."""
        response = rest_api.get(f'{TEMPLATE_URL}/{TYPE_ID}', unauthorized=True)

        assert response.status_code == HTTPStatus.UNAUTHORIZED
