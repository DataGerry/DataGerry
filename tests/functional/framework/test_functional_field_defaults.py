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
Functional coverage of field defaults: filled on create, and held to the field's own rules on write

A new object's empty field takes its type's default - on `POST /objects/` and on an object import -
whether or not the client sent it; an update keeps what the client sent. A default that breaks its own
field's rules is refused by `POST`/`PUT /types/` and `POST /section_templates/`, dropped by the type
import, and - for one stored before those rules - never filled into a new object
"""
import json
from http import HTTPStatus
from io import BytesIO
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.object_field_value_constants import FieldDefaultError
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType, SectionType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9661
LEGACY_TYPE_ID: int = 9662
OBJECT_ID: int = 9671
IMPORTED_TYPE_NAME: str = 'defaults-imported'
TEMPLATE_NAME: str = 'defaults-template'
ALL_TYPE_IDS: list[int] = [TYPE_ID, LEGACY_TYPE_ID]

NOTE_FIELD: str = 'dflt-note'
COUNT_FIELD: str = 'dflt-count'
CODE_FIELD: str = 'dflt-code'
CODE_REGEX: str = '[A-Z]+'
NOTE_DEFAULT: str = 'no note'
COUNT_DEFAULT: int = 3


def _fields(code_default: Any = 'ABC') -> list[dict[str, Any]]:
    """A defaulted text field, a defaulted number field and a patterned, defaulted code field."""
    return [
        {'type': 'text', 'name': NOTE_FIELD, 'label': 'Note', 'value': NOTE_DEFAULT},
        {'type': 'number', 'name': COUNT_FIELD, 'label': 'Count', 'value': COUNT_DEFAULT},
        {'type': 'text', 'name': CODE_FIELD, 'label': 'Code', 'regex': CODE_REGEX, 'value': code_default},
    ]


def _sections() -> list[dict[str, Any]]:
    """One section showing the three fields."""
    return [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main',
             'fields': [NOTE_FIELD, COUNT_FIELD, CODE_FIELD]}]


def _type_payload(public_id: int, code_default: Any = 'ABC') -> dict[str, Any]:
    """A POST / PUT /types/ body."""
    doc: dict[str, Any] = make_type_doc(public_id, f'defaults-{public_id}', fields=_fields(code_default),
                                        sections=_sections())
    doc.pop('creation_time', None)
    return doc


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the defaulted type; removes every type, object, template and log this module creates."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'$or': [{'public_id': {'$in': ALL_TYPE_IDS}}, {'name': IMPORTED_TYPE_NAME}]})
        objects.delete_many({'type_id': {'$in': ALL_TYPE_IDS}})
        templates.delete_many({'name': TEMPLATE_NAME})
        database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
            {'object_id': {'$in': [OBJECT_ID]}}
        )

    _purge()
    types.insert_one(make_type_doc(TYPE_ID, 'defaults-type', fields=_fields(), sections=_sections()))
    yield types, objects, templates
    _purge()


def _object_payload(fields: list[dict[str, Any]], type_id: int = TYPE_ID) -> dict[str, Any]:
    """A POST /objects/ body."""
    return {'public_id': OBJECT_ID, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': fields}


def _stored_values(objects, public_id: int = OBJECT_ID) -> dict[str, Any]:
    """The stored object's values by field name."""
    stored: dict[str, Any] = objects.find_one({'public_id': public_id})

    return {field['name']: field.get('value') for field in stored['fields']}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             THE FILL, ON CREATE ONLY                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateFillsEmptyFields:
    """POST /objects/."""

    def test_omitted_fields_take_their_defaults(self, rest_api, db) -> None:
        """Whether or not the client sent the default"""
        _, objects, _ = db

        assert rest_api.post('/objects/', json=_object_payload([])).status_code == HTTPStatus.OK
        assert _stored_values(objects) == {NOTE_FIELD: NOTE_DEFAULT, COUNT_FIELD: COUNT_DEFAULT, CODE_FIELD: 'ABC'}

    @pytest.mark.parametrize('empty', [None, ''], ids=['null', 'empty-string'])
    def test_an_empty_value_takes_the_default(self, rest_api, db, empty: Any) -> None:
        """Empty is absent, null or ''"""
        _, objects, _ = db

        rest_api.post('/objects/', json=_object_payload([{'type': 'text', 'name': NOTE_FIELD, 'value': empty}]))

        assert _stored_values(objects)[NOTE_FIELD] == NOTE_DEFAULT

    def test_a_chosen_zero_is_kept(self, rest_api, db) -> None:
        """0 is a value"""
        _, objects, _ = db

        rest_api.post('/objects/', json=_object_payload([{'type': 'number', 'name': COUNT_FIELD, 'value': 0}]))

        assert _stored_values(objects)[COUNT_FIELD] == 0

    def test_an_update_keeps_a_cleared_field(self, rest_api, db) -> None:
        """Create only - a user can still clear a field that has a default"""
        _, objects, _ = db
        rest_api.post('/objects/', json=_object_payload([]))

        response = rest_api.put(f'/objects/{OBJECT_ID}', json=_object_payload([
            {'type': 'text', 'name': NOTE_FIELD, 'value': ''},
            {'type': 'number', 'name': COUNT_FIELD, 'value': COUNT_DEFAULT},
            {'type': 'text', 'name': CODE_FIELD, 'value': 'ABC'},
        ]))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_values(objects)[NOTE_FIELD] == ''

    def test_a_legacy_default_breaking_its_rule_is_not_filled(self, rest_api, db) -> None:
        """Stored before the rule: the create that leaves the field empty does not fail over it"""
        types, objects, _ = db
        types.insert_one(make_type_doc(LEGACY_TYPE_ID, 'defaults-legacy', fields=_fields(code_default='abc'),
                                       sections=_sections()))

        response = rest_api.post('/objects/', json=_object_payload([], type_id=LEGACY_TYPE_ID))

        assert response.status_code == HTTPStatus.OK
        assert CODE_FIELD not in _stored_values(objects)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        A DEFAULT HAS TO PASS ITS OWN RULES                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTypeWrites:
    """POST / PUT /types/."""

    def test_a_create_with_a_bad_default_is_refused(self, rest_api, db) -> None:
        """400 naming the field and the pattern"""
        response = rest_api.post('/types/', json=_type_payload(LEGACY_TYPE_ID, code_default='abc'))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == FieldDefaultError.PATTERN_MISMATCH.format(
            field=CODE_FIELD, regex=CODE_REGEX)

    def test_a_stored_bad_default_is_refused_on_its_next_save(self, rest_api, db) -> None:
        """The type is saved unchanged - and refused until the default is fixed"""
        types, _, _ = db
        types.update_one({'public_id': TYPE_ID, 'fields.name': CODE_FIELD}, {'$set': {'fields.$.value': 'abc'}})

        assert rest_api.put(f'/types/{TYPE_ID}', json=_type_payload(TYPE_ID, code_default='abc')).status_code \
            == HTTPStatus.BAD_REQUEST
        assert rest_api.put(f'/types/{TYPE_ID}', json=_type_payload(TYPE_ID, code_default='XYZ')).status_code \
            == HTTPStatus.ACCEPTED


class TestSectionTemplateWrite:
    """POST /section_templates/."""

    def test_a_template_with_a_bad_default_is_refused(self, rest_api, db) -> None:
        """It would be inlined and propagated into every consuming type's objects"""
        _, _, templates = db
        fields = [{'type': 'text', 'name': CODE_FIELD, 'label': 'Code', 'regex': CODE_REGEX, 'value': 'abc'}]
        params = {'name': TEMPLATE_NAME, 'label': 'Defaults', 'type': SectionType.SECTION.value,
                  'is_global': 'false', 'predefined': 'false', 'fields': json.dumps(fields)}

        response = rest_api.post('/section_templates/', query_string=params)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert templates.find_one({'name': TEMPLATE_NAME}) is None


class TestTypeImport:
    """POST /import/type/create/ repairs instead of refusing."""

    def test_a_bad_default_is_dropped_and_the_type_imported(self, rest_api, db) -> None:
        """The field and its rule stay; the default goes"""
        types, _, _ = db
        payload: dict[str, Any] = _type_payload(0, code_default='abc')
        payload.pop('public_id')
        payload['name'] = IMPORTED_TYPE_NAME

        response = rest_api.post('/import/type/create/', data={'uploadFile': json.dumps([payload], default=str)},
                                 content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        stored: dict[str, Any] = types.find_one({'name': IMPORTED_TYPE_NAME})
        code = next(field for field in stored['fields'] if field['name'] == CODE_FIELD)
        assert code.get('value') is None
        assert code['regex'] == CODE_REGEX


class TestObjectImport:
    """POST /import/object fills an imported row like a create."""

    def test_an_empty_cell_takes_the_default(self, rest_api, db) -> None:
        """The CSV maps only the note column, and leaves it empty"""
        _, objects, _ = db
        form = {
            'file': (BytesIO(b'note\n\n'), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({'header': True}),
            'importer_config': json.dumps({'type_id': TYPE_ID,
                                           'mapping': [{'name': NOTE_FIELD, 'value': 0, 'type': 'field'}]}),
        }

        response = rest_api.post('/import/object/', data=form, content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        imported = [obj for obj in objects.find({'type_id': TYPE_ID})]
        assert imported
        values = {field['name']: field.get('value') for field in imported[0]['fields']}
        assert values[NOTE_FIELD] == NOTE_DEFAULT
        assert values[COUNT_FIELD] == COUNT_DEFAULT
