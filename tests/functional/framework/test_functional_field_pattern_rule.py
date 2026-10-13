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
Functional coverage of the field pattern rule on every write that declares field patterns

`POST` / `PUT /types/`, `POST` / `PUT /section_templates/` and both type-import verbs refuse a field ``regex`` the
browser and the server read differently (or only one of them accepts, or that is not text) - naming the field and the
construct - while a pattern a stored type or template already carries stays saveable. Nothing refused is stored
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.field_pattern_rule import field_pattern_problem
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType, SectionType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9681
LEGACY_TYPE_ID: int = 9682
TEMPLATE_ID: int = 9691
IMPORTED_TYPE_NAME: str = 'pattern-imported'
TEMPLATE_NAME: str = 'pattern-template'
CODE_FIELD: str = 'pat-code'
PORTABLE: str = '[A-Z]{2}[0-9]+'
REFUSED: dict[str, str] = {
    'unicode-property': r'\p{L}+', 'inline-flag': '(?i)ab', 'possessive': 'a++', 'open-lower-bound': 'x{,3}',
    'code-point-escape': r'\u{41}', 'empty-negated-class': '[^]', 'not-compilable': '(',
}
REFUSED_IDS: list[str] = list(REFUSED)
REFUSED_PATTERNS: list[str] = list(REFUSED.values())


def _fields(regex: Any) -> list[dict[str, Any]]:
    """One patterned text field."""
    return [{'type': 'text', 'name': CODE_FIELD, 'label': 'Code', 'regex': regex}]


def _type_payload(public_id: int, regex: Any) -> dict[str, Any]:
    """A POST / PUT /types/ body."""
    sections = [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [CODE_FIELD]}]
    doc: dict[str, Any] = make_type_doc(public_id, f'pattern-{public_id}', fields=_fields(regex), sections=sections)
    doc.pop('creation_time', None)
    return doc


def _template_params(regex: Any, public_id: int | None = None) -> dict[str, str]:
    """A POST / PUT /section_templates/ query."""
    params = {'name': TEMPLATE_NAME, 'label': 'Pattern', 'type': SectionType.SECTION.value, 'is_global': 'false',
              'predefined': 'false', 'fields': json.dumps(_fields(regex))}

    if public_id is not None:
        params['public_id'] = str(public_id)

    return params


def _refused(response, regex: Any) -> None:
    """A 400 carrying the rule's own message"""
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert field_pattern_problem(CODE_FIELD, regex) in response.get_json()['message']


def _import_errors(response) -> list[str]:
    """Every error the import's partial report collected."""
    return [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]


def _upload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The multipart form of a type import."""
    return {'uploadFile': json.dumps(entries, default=str)}


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str):
    """A type with a portable pattern and one already storing a refused pattern; cleaned after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'$or': [{'public_id': {'$in': [TYPE_ID, LEGACY_TYPE_ID]}}, {'name': IMPORTED_TYPE_NAME}]})
        templates.delete_many({'$or': [{'name': TEMPLATE_NAME}, {'public_id': TEMPLATE_ID}]})

    _purge()
    types.insert_many([make_type_doc(TYPE_ID, f'pattern-{TYPE_ID}', fields=_fields(PORTABLE)),
                       make_type_doc(LEGACY_TYPE_ID, f'pattern-{LEGACY_TYPE_ID}', fields=_fields(REFUSED_PATTERNS[0]))])
    yield types, templates
    _purge()


class TestTypeRoutes:
    """POST and PUT /types/"""

    @pytest.mark.parametrize('regex', REFUSED_PATTERNS, ids=REFUSED_IDS)
    def test_a_create_with_a_refused_pattern_is_a_400(self, rest_api, db, regex: str) -> None:
        """Nothing stored"""
        payload = _type_payload(0, regex)
        payload.pop('public_id')
        payload['name'] = IMPORTED_TYPE_NAME

        _refused(rest_api.post('/types/', json=payload), regex)
        assert db[0].find_one({'name': IMPORTED_TYPE_NAME}) is None

    @pytest.mark.usefixtures('db')
    def test_a_pattern_that_is_no_text_is_refused_by_the_type_schema(self, rest_api) -> None:
        """The type write schema types the key before the rule runs"""
        payload = _type_payload(0, 5)
        payload.pop('public_id')
        payload['name'] = IMPORTED_TYPE_NAME

        response = rest_api.post('/types/', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'regex' in response.get_json()['message']

    @pytest.mark.usefixtures('db')
    def test_a_section_template_pattern_that_is_no_text_is_refused_by_the_rule(self, rest_api) -> None:
        """The template's field list has no schema - the rule answers"""
        _refused(rest_api.post('/section_templates/', query_string=_template_params(5)), 5)

    @pytest.mark.parametrize('regex', REFUSED_PATTERNS, ids=REFUSED_IDS)
    def test_an_update_changing_to_a_refused_pattern_is_a_400(self, rest_api, db, regex: str) -> None:
        """The stored pattern stays"""
        _refused(rest_api.put(f'/types/{TYPE_ID}', json=_type_payload(TYPE_ID, regex)), regex)
        assert db[0].find_one({'public_id': TYPE_ID})['fields'][0]['regex'] == PORTABLE

    @pytest.mark.usefixtures('db')
    def test_an_update_keeping_a_stored_refused_pattern_is_saved(self, rest_api) -> None:
        """A stored refused pattern stays saveable until somebody edits that pattern"""
        payload = _type_payload(LEGACY_TYPE_ID, REFUSED_PATTERNS[0])
        payload['label'] = 'Edited'

        assert rest_api.put(f'/types/{LEGACY_TYPE_ID}', json=payload).status_code == HTTPStatus.ACCEPTED

    @pytest.mark.usefixtures('db')
    def test_a_portable_pattern_is_stored(self, rest_api) -> None:
        """The control"""
        assert rest_api.put(f'/types/{TYPE_ID}', json=_type_payload(TYPE_ID, r'\d{3}-[a-z]+')).status_code == \
            HTTPStatus.ACCEPTED


class TestSectionTemplateRoutes:
    """POST and PUT /section_templates/"""

    @pytest.mark.parametrize('regex', REFUSED_PATTERNS, ids=REFUSED_IDS)
    def test_a_create_with_a_refused_pattern_is_a_400(self, rest_api, db, regex: str) -> None:
        """Nothing stored"""
        _refused(rest_api.post('/section_templates/', query_string=_template_params(regex)), regex)
        assert db[1].find_one({'name': TEMPLATE_NAME}) is None

    def test_an_update_keeping_a_stored_refused_pattern_is_saved(self, rest_api, db) -> None:
        """Judged against the stored template"""
        db[1].insert_one({'public_id': TEMPLATE_ID, 'name': TEMPLATE_NAME, 'label': 'Pattern', 'predefined': False,
                          'is_global': False, 'type': SectionType.SECTION.value,
                          'fields': _fields(REFUSED_PATTERNS[0])})

        response = rest_api.put('/section_templates/', query_string=_template_params(REFUSED_PATTERNS[0], TEMPLATE_ID))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_an_update_changing_to_a_refused_pattern_is_a_400(self, rest_api, db) -> None:
        """A changed pattern is judged"""
        db[1].insert_one({'public_id': TEMPLATE_ID, 'name': TEMPLATE_NAME, 'label': 'Pattern', 'predefined': False,
                          'is_global': False, 'type': SectionType.SECTION.value, 'fields': _fields(PORTABLE)})

        _refused(rest_api.put('/section_templates/', query_string=_template_params(REFUSED_PATTERNS[1], TEMPLATE_ID)),
                 REFUSED_PATTERNS[1])
        assert db[1].find_one({'public_id': TEMPLATE_ID})['fields'][0]['regex'] == PORTABLE


class TestTypeImport:
    """POST /import/type/create/ and /import/type/update/ - the entry is reported, the rest imported"""

    def test_a_create_entry_with_a_refused_pattern_is_reported(self, rest_api, db) -> None:
        """Not imported"""
        payload = _type_payload(0, REFUSED_PATTERNS[1])
        payload.pop('public_id')
        payload['name'] = IMPORTED_TYPE_NAME

        response = rest_api.post('/import/type/create/', data=_upload([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert field_pattern_problem(CODE_FIELD, REFUSED_PATTERNS[1]) in ' '.join(_import_errors(response))
        assert db[0].find_one({'name': IMPORTED_TYPE_NAME}) is None

    def test_an_update_entry_changing_to_a_refused_pattern_is_reported(self, rest_api, db) -> None:
        """The stored pattern stays"""
        response = rest_api.post('/import/type/update/', data=_upload([_type_payload(TYPE_ID, REFUSED_PATTERNS[2])]),
                                 content_type='multipart/form-data')

        assert field_pattern_problem(CODE_FIELD, REFUSED_PATTERNS[2]) in ' '.join(_import_errors(response))
        assert db[0].find_one({'public_id': TYPE_ID})['fields'][0]['regex'] == PORTABLE

    @pytest.mark.usefixtures('db')
    def test_an_update_entry_keeping_a_stored_refused_pattern_is_imported(self, rest_api) -> None:
        """As on the update route"""
        response = rest_api.post('/import/type/update/',
                                 data=_upload([_type_payload(LEGACY_TYPE_ID, REFUSED_PATTERNS[0])]),
                                 content_type='multipart/form-data')

        assert not _import_errors(response)
