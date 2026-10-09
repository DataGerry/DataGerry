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
Functional tests of the identifier rule on the type write paths

Through the real routes: ``POST /types/`` refuses a new blank, padded or bracketed field or section identifier with a
400 naming it, and accepts the names the type builder produces (dots, umlauts); ``PUT /types/<id>`` keeps an odd
identifier the stored type already holds and refuses one it adds; the type import reports the same message per entry.
And the reason for the bracket rule, end to end: a field's identifier is written into the object-import template's
header, and a usable name (dots and umlauts included) is read back from it intact
"""
import csv
import io
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.importer.parser.csv_object_parser import normalize_csv_header
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_constants import IdentifierKind, TypeIdentifierError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

CREATE_TYPE_ID: int = 96501
STORED_TYPE_ID: int = 96502
IMPORT_TYPE_NAME: str = 'identifier-import'
ALL_TYPE_IDS: list[int] = [CREATE_TYPE_ID, STORED_TYPE_ID]
ALL_TYPE_NAMES: list[str] = ['identifier-create', 'identifier-stored', IMPORT_TYPE_NAME, 'identifier-usable']

BRACKETED: str = 'size-[gb]'
USABLE_NAMES: list[str] = ['ip.address', 'größe', 'cpu-(ghz)']


def _field(name: str) -> dict[str, Any]:
    """A text field"""
    return {'type': 'text', 'name': name, 'label': name}


def _type_payload(public_id: int, name: str, field_names: list[str], section_name: str = 'main') -> dict[str, Any]:
    """A POST / PUT /types/ body"""
    doc: dict[str, Any] = make_type_doc(public_id, name, fields=[_field(field) for field in field_names], sections=[
        {'type': 'section', 'name': section_name, 'label': 'Main', 'fields': field_names},
    ])
    doc.pop('creation_time', None)

    return doc


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """The types collection; every type this module creates is removed around each test"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({'$or': [{'public_id': {'$in': ALL_TYPE_IDS}}, {'name': {'$in': ALL_TYPE_NAMES}}]})

    _purge()
    yield collection
    _purge()


class TestTheCreateRoute:
    """POST /types/: every identifier is new."""

    @pytest.mark.parametrize('name, problem', [
        ('', TypeIdentifierError.BLANK),
        (' cpu', TypeIdentifierError.SURROUNDING_WHITESPACE),
        (BRACKETED, TypeIdentifierError.FORBIDDEN_CHARACTER),
    ], ids=['blank', 'padded', 'bracketed'])
    def test_a_refused_field_identifier_is_a_400_naming_it(
        self, rest_api, types, name: str, problem: TypeIdentifierError,
    ) -> None:
        """Nothing is stored"""
        response = rest_api.post('/types/', json=_type_payload(CREATE_TYPE_ID, 'identifier-create', [name]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == problem.format(kind=IdentifierKind.FIELD.value, name=name)
        assert types.count_documents({'name': 'identifier-create'}) == 0

    def test_a_blank_section_identifier_is_a_400(self, rest_api, types) -> None:
        """Sections follow the same rule"""
        response = rest_api.post('/types/', json=_type_payload(CREATE_TYPE_ID, 'identifier-create', ['a'], ''))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TypeIdentifierError.BLANK.format(
            kind=IdentifierKind.SECTION.value, name='')

    def test_the_names_the_builder_produces_are_accepted(self, rest_api, types) -> None:
        """Dots, umlauts, parentheses - what a label becomes"""
        response = rest_api.post('/types/', json=_type_payload(CREATE_TYPE_ID, 'identifier-usable', USABLE_NAMES))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        stored: dict[str, Any] = types.find_one({'name': 'identifier-usable'})
        assert [field['name'] for field in stored['fields']] == USABLE_NAMES


class TestTheUpdateRoute:
    """PUT /types/<id>: only the identifiers the update adds are judged."""

    @pytest.fixture(autouse=True)
    def _stored(self, types) -> None:
        """A type stored before the rule, holding a bracketed field"""
        types.insert_one(make_type_doc(STORED_TYPE_ID, 'identifier-stored', fields=[_field(BRACKETED)], sections=[
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [BRACKETED]},
        ]))

    def test_keeping_a_stored_odd_identifier_passes(self, rest_api, types) -> None:
        """Immutable - it cannot be renamed, so it must not block a save"""
        response = rest_api.put(f'/types/{STORED_TYPE_ID}',
                                json=_type_payload(STORED_TYPE_ID, 'identifier-stored', [BRACKETED]))

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_adding_a_refused_identifier_is_a_400(self, rest_api, types) -> None:
        """The added one is new, and judged"""
        response = rest_api.put(f'/types/{STORED_TYPE_ID}',
                                json=_type_payload(STORED_TYPE_ID, 'identifier-stored', [BRACKETED, ' ram']))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TypeIdentifierError.SURROUNDING_WHITESPACE.format(
            kind=IdentifierKind.FIELD.value, name=' ram')
        assert [field['name'] for field in types.find_one({'public_id': STORED_TYPE_ID})['fields']] == [BRACKETED]


class TestTheTypeImport:
    """POST /import/type/create/: the same rule, reported per entry."""

    def test_a_bracketed_identifier_is_reported_and_not_imported(self, rest_api, types) -> None:
        """The entry fails with the route's message; nothing is created"""
        entry: dict[str, Any] = _type_payload(CREATE_TYPE_ID, IMPORT_TYPE_NAME, [BRACKETED])
        entry.pop('public_id', None)

        response = rest_api.post('/import/type/create/', data={'uploadFile': json.dumps([entry], default=str)},
                                 content_type='multipart/form-data')

        errors: list[str] = [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]
        assert TypeIdentifierError.FORBIDDEN_CHARACTER.format(kind=IdentifierKind.FIELD.value, name=BRACKETED) in errors
        assert types.count_documents({'name': IMPORT_TYPE_NAME}) == 0


class TestTheImportTemplateRoundTrip:
    """Why brackets are refused and dots are not: the template header carries the identifier."""

    def test_usable_names_are_read_back_from_the_template_header(self, rest_api, types) -> None:
        """The downloaded template's header resolves to the field identifiers, dots and umlauts intact"""
        assert rest_api.post('/types/', json=_type_payload(CREATE_TYPE_ID, 'identifier-usable', USABLE_NAMES)) \
            .status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        type_id: int = types.find_one({'name': 'identifier-usable'})['public_id']

        response = rest_api.get(f'/exporter/template/{type_id}')
        header: list[str] = next(csv.reader(io.StringIO(response.get_data(as_text=True))))

        assert set(USABLE_NAMES) <= set(normalize_csv_header(header))
