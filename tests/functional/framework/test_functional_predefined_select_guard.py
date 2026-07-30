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
Functional coverage for the predefined-section-template select-option guard

An unknown value of a select field normally extends that field's options on the CmdbType. A select
field belonging to a *predefined* CmdbSectionTemplate is exempt: the template is immutable (the
/section_templates routes refuse to edit it) and the next template propagation would revert any local
edit, so the value is rejected instead of silently editing the type.

Asserted end to end here: POST /objects/ and PUT /objects/<id> return 400 and leave the type's
options untouched, an import reports the row in failed_imports without extending the type, and a
value the template already offers still passes on every one of those routes. A select field that is
NOT owned by a predefined template is still extended, so the guard did not disable the feature
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from io import BytesIO
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.section_template_model import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from tests.utils.ipam_doc_builders import make_type_doc, make_object_doc, make_field
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
IMPORT_URL: str = '/import/object'

TEMPLATE_ID: int = 9651
TEMPLATE_NAME: str = 'func-predefined-tpl'

TYPE_ID: int = 9652
TYPE_NAME: str = 'predefined-guard-type'

PROTECTED_SELECT_FIELD: str = 'func-tpl-orientation'   # owned by the predefined template
OWN_SELECT_FIELD: str = 'func-own-select'              # the type's own field, still extendable
OWN_SECTION: str = 'information'

KNOWN_OPTION: str = 'horizontal'                       # an option the predefined template offers
OTHER_KNOWN_OPTION: str = 'vertical'                   # the template's second option
UNKNOWN_OPTION: str = 'Horizontal'                     # differs in case only - the corruption vector
NEW_OWN_OPTION: str = 'brand-new'                      # accepted on the type's own select field

# The full option set the predefined template defines - it must survive every write attempt unchanged
TEMPLATE_OPTIONS: set[str] = {KNOWN_OPTION, OTHER_KNOWN_OPTION}

OBJECT_ID_FOR_CREATE: int = 9661
OBJECT_ID_FOR_UPDATE: int = 9662
ALL_OBJECT_IDS: list[int] = [OBJECT_ID_FOR_CREATE, OBJECT_ID_FOR_UPDATE]

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'


def _template_doc() -> dict[str, Any]:
    """Builds the predefined, global CmdbSectionTemplate carrying the protected select field."""
    return {
        'public_id': TEMPLATE_ID,
        'name': TEMPLATE_NAME,
        'label': 'Predefined Guard Template',
        'type': SectionType.SECTION.value,
        'is_global': True,
        'predefined': True,
        'fields': [{
            'type': FieldType.SELECT.value,
            'name': PROTECTED_SELECT_FIELD,
            'label': 'Orientation',
            'options': [
                {'name': KNOWN_OPTION, 'label': 'Horizontal'},
                {'name': OTHER_KNOWN_OPTION, 'label': 'Vertical'},
            ],
        }],
    }


def _type_doc() -> dict[str, Any]:
    """Builds the CmdbType using the predefined template, plus one select field of its own."""
    return make_type_doc(
        TYPE_ID,
        TYPE_NAME,
        fields=[
            {
                'type': FieldType.SELECT.value,
                'name': PROTECTED_SELECT_FIELD,
                'label': 'Orientation',
                'options': [
                    {'name': KNOWN_OPTION, 'label': 'Horizontal'},
                    {'name': OTHER_KNOWN_OPTION, 'label': 'Vertical'},
                ],
            },
            {
                'type': FieldType.SELECT.value,
                'name': OWN_SELECT_FIELD,
                'label': 'Own',
                'options': [{'name': 'a', 'label': 'A'}],
            },
        ],
        sections=[
            {
                'type': SectionType.SECTION.value,
                'name': TEMPLATE_NAME,
                'label': 'Predefined Guard Template',
                'fields': [PROTECTED_SELECT_FIELD],
            },
            {
                'type': SectionType.SECTION.value,
                'name': OWN_SECTION,
                'label': 'Information',
                'fields': [OWN_SELECT_FIELD],
            },
        ],
        global_template_ids=[TEMPLATE_NAME],
    )


def _object_payload(public_id: int, protected_value: str, own_value: str = 'a') -> dict[str, Any]:
    """Builds a CmdbObject payload for POST /objects/ and PUT /objects/<id>."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': FieldType.SELECT.value, 'name': PROTECTED_SELECT_FIELD, 'value': protected_value},
            {'type': FieldType.SELECT.value, 'name': OWN_SELECT_FIELD, 'value': own_value},
        ],
    }


def _import_form(csv_body: bytes, field_name: str) -> dict[str, Any]:
    """Builds the multipart import form data mapping the single CSV column onto the given field."""
    return {
        'file': (BytesIO(csv_body), 'import.csv'),
        'file_format': 'csv',
        'parser_config': json.dumps({}),
        'importer_config': json.dumps({
            'type_id': TYPE_ID,
            'mapping': [{'name': field_name, 'value': 0, 'type': 'field'}],
        }),
    }


def _stored_options(database_manager: MongoDatabaseManager, database_name: str, field_name: str) -> set[str]:
    """Reads the option names currently stored on one of the type's select fields."""
    stored_type = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
        .find_one({'public_id': TYPE_ID})
    field = next(item for item in stored_type['fields'] if item['name'] == field_name)

    return {option['name'] for option in field.get('options', [])}


@pytest.fixture(autouse=True)
def _seed_template_and_type(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the predefined template + the consuming type fresh per test and cleans up after."""
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    templates.insert_one(_template_doc())
    types.insert_one(_type_doc())
    yield

    imported_ids = [doc['public_id'] for doc in objects.find({'type_id': TYPE_ID})]

    templates.delete_one({'public_id': TEMPLATE_ID})
    types.delete_one({'public_id': TYPE_ID})
    objects.delete_many({'type_id': TYPE_ID})
    # A successful import / create writes a log per object; left behind they pile up in the collection
    # every other log test pages through
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)\
        .delete_many({'object_id': {'$in': imported_ids + ALL_OBJECT_IDS}})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    OBJECT CREATE                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateObject:
    """POST /objects/ refuses a value that would extend a predefined template's select field."""

    def test_unknown_value_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The object is not created and the predefined template's options are untouched."""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_object_payload(OBJECT_ID_FOR_CREATE, UNKNOWN_OPTION))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_options(database_manager, database_name, PROTECTED_SELECT_FIELD) == TEMPLATE_OPTIONS

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        assert objects.count_documents({'public_id': OBJECT_ID_FOR_CREATE}) == 0

    def test_error_names_the_template(self, rest_api) -> None:
        """The rejection tells the user which predefined template blocks the value."""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_object_payload(OBJECT_ID_FOR_CREATE, UNKNOWN_OPTION))

        assert TEMPLATE_NAME in json.dumps(response.get_json())

    def test_known_value_is_created(self, rest_api) -> None:
        """A value the predefined template already offers creates the object as before."""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_object_payload(OBJECT_ID_FOR_CREATE, KNOWN_OPTION))

        assert response.status_code == HTTPStatus.OK

    def test_the_types_own_select_field_is_still_extended(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A select field owned by no predefined template keeps the extend-on-write behaviour."""
        response = rest_api.post(
            f'{OBJECTS_URL}/',
            json=_object_payload(OBJECT_ID_FOR_CREATE, KNOWN_OPTION, own_value=NEW_OWN_OPTION),
        )

        assert response.status_code == HTTPStatus.OK
        assert NEW_OWN_OPTION in _stored_options(database_manager, database_name, OWN_SELECT_FIELD)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    OBJECT UPDATE                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateObject:
    """PUT /objects/<id> applies the same guard before the object is written."""

    @pytest.fixture(autouse=True)
    def _seed_object(self, database_manager: MongoDatabaseManager, database_name: str):
        """Stores one object of the guarded type carrying a valid value."""
        doc = make_object_doc(
            OBJECT_ID_FOR_UPDATE,
            TYPE_ID,
            [make_field(PROTECTED_SELECT_FIELD, KNOWN_OPTION), make_field(OWN_SELECT_FIELD, 'a')],
        )
        doc['creation_time'] = datetime.now(timezone.utc)
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(doc)

    def test_unknown_value_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The stored value stays as it was and no option is added to the type."""
        response = rest_api.put(
            f'{OBJECTS_URL}/{OBJECT_ID_FOR_UPDATE}',
            json=_object_payload(OBJECT_ID_FOR_UPDATE, UNKNOWN_OPTION),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_options(database_manager, database_name, PROTECTED_SELECT_FIELD) == TEMPLATE_OPTIONS

        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': OBJECT_ID_FOR_UPDATE})
        stored_values = {field['name']: field['value'] for field in stored['fields']}

        assert stored_values[PROTECTED_SELECT_FIELD] == KNOWN_OPTION

    def test_known_value_is_updated(self, rest_api) -> None:
        """Switching to another option the template offers is accepted."""
        response = rest_api.put(
            f'{OBJECTS_URL}/{OBJECT_ID_FOR_UPDATE}',
            json=_object_payload(OBJECT_ID_FOR_UPDATE, OTHER_KNOWN_OPTION),
        )

        assert response.status_code == HTTPStatus.ACCEPTED


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    OBJECT IMPORT                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestImportObject:
    """POST /import/object rejects the row per object instead of editing the predefined template."""

    def test_unknown_value_is_reported_per_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The row lands in failed_imports, nothing is imported and the type is untouched."""
        csv_body = f'{PROTECTED_SELECT_FIELD}\n{UNKNOWN_OPTION}\n'.encode()

        response = rest_api.post(
            f'{IMPORT_URL}/', data=_import_form(csv_body, PROTECTED_SELECT_FIELD),
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK

        body = response.get_json()

        assert body['success_imports'] == 0
        (failure,) = body['failed_imports']
        assert any(TEMPLATE_NAME in error for error in failure['errors'])
        assert _stored_options(database_manager, database_name, PROTECTED_SELECT_FIELD) == TEMPLATE_OPTIONS
        assert database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .count_documents({'type_id': TYPE_ID}) == 0

    def test_known_value_is_imported(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A value the predefined template offers imports normally."""
        csv_body = f'{PROTECTED_SELECT_FIELD}\n{KNOWN_OPTION}\n'.encode()

        response = rest_api.post(
            f'{IMPORT_URL}/', data=_import_form(csv_body, PROTECTED_SELECT_FIELD),
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK

        body = response.get_json()

        assert body['failed_imports'] == []
        assert body['success_imports'] == 1
        assert _stored_options(database_manager, database_name, PROTECTED_SELECT_FIELD) == TEMPLATE_OPTIONS

    def test_the_types_own_select_field_is_still_extended(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An unknown value of the type's own select field is still added to the type by the import."""
        csv_body = f'{OWN_SELECT_FIELD}\n{NEW_OWN_OPTION}\n'.encode()

        response = rest_api.post(
            f'{IMPORT_URL}/', data=_import_form(csv_body, OWN_SELECT_FIELD),
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['failed_imports'] == []
        assert NEW_OWN_OPTION in _stored_options(database_manager, database_name, OWN_SELECT_FIELD)
