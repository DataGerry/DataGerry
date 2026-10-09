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
Functional tests for a CmdbType's copy of a global section template: the copy is the template's

``POST /types/``, ``PUT /types/<id>`` and the type import (``/import/type/create/``), with the predefined
``dg-modelspec`` template and a non-predefined global one. Pinned:

  - a drifted copy (a rewritten label, a changed field kind, a dropped field, the section's label) is stored as the
    template's - on create, on update and on import, for a predefined and a non-predefined global template alike
  - a frontend-faithful copy is stored exactly as sent
  - a claimed template the type carries no section for gets the section
  - a field the template does not own inside its section is a 400 (an import refusal), and nothing is written
  - a claim naming no stored template is dropped; on update the section and fields it named stay, with the
    objects' values - it is not the user removing a template
"""
import json
from copy import deepcopy
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.section_templates.section_template_creator import SectionTemplateCreator
from cmdb.models.object_model import CmdbObject
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TEMPLATE_SECTION_FOREIGN_FIELD_MESSAGE,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import TypeImportError

from tests.functional.framework.test_functional_types_route import NAME_FIELD, _type_payload
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types/'
IMPORT_CREATE_URL: str = '/import/type/create/'

PREDEFINED_NAME: str = 'dg-modelspec'
PREDEFINED_TEMPLATE: dict[str, Any] = next(
    template for template in SectionTemplateCreator().get_predefined_templates() if template['name'] == PREDEFINED_NAME
)
GLOBAL_NAME: str = 't30-global-contact'
GLOBAL_TEMPLATE: dict[str, Any] = {
    'name': GLOBAL_NAME, 'label': 'Contact', 'type': 'section', 'is_global': True, 'predefined': False,
    'fields': [{'type': 'text', 'name': 't30-contact-phone', 'label': 'Phone'}],
}
UNKNOWN_TEMPLATE: str = 't30-no-such-template'

PREDEFINED_TEMPLATE_ID: int = 89951
GLOBAL_TEMPLATE_ID: int = 89952
TYPE_NAMES: list[str] = ['t30-created', 't30-stored', 't30-imported', 't30-import-refused']
STORED_OBJECT_ID: int = 89961
LEFTOVER_FIELD: str = 't30-leftover'
FOREIGN_FIELD: str = 't30-foreign'


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The two templates (the predefined one only when absent), purged with every type and object written"""
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    inserted_predefined: bool = templates.count_documents({'name': PREDEFINED_NAME}) == 0

    if inserted_predefined:
        templates.insert_one({**deepcopy(PREDEFINED_TEMPLATE), 'public_id': PREDEFINED_TEMPLATE_ID})

    templates.delete_many({'name': GLOBAL_NAME})
    templates.insert_one({**deepcopy(GLOBAL_TEMPLATE), 'public_id': GLOBAL_TEMPLATE_ID})
    types.delete_many({'name': {'$in': TYPE_NAMES}})
    objects.delete_many({'public_id': STORED_OBJECT_ID})

    yield {'templates': templates, 'types': types, 'objects': objects}

    types.delete_many({'name': {'$in': TYPE_NAMES}})
    objects.delete_many({'public_id': STORED_OBJECT_ID})
    templates.delete_many({'name': GLOBAL_NAME})

    if inserted_predefined:
        templates.delete_one({'public_id': PREDEFINED_TEMPLATE_ID})


def _claiming(name: str, *templates: dict[str, Any]) -> dict[str, Any]:
    """A type payload carrying a faithful copy of each template"""
    payload: dict[str, Any] = _type_payload(0, name)
    payload.pop('public_id')
    payload['name'] = name
    payload['global_template_ids'] = [template['name'] for template in templates]

    for template in templates:
        payload['fields'] += deepcopy(template['fields'])
        payload['render_meta']['sections'].append({
            'type': template['type'], 'name': template['name'], 'label': template['label'],
            'fields': [field['name'] for field in template['fields']],
        })

    return payload


def _with_foreign_field(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload with a field of its own placed inside the predefined template's section"""
    foreign: dict[str, Any] = deepcopy(payload)
    foreign['fields'].append({'type': 'text', 'name': FOREIGN_FIELD, 'label': 'Foreign'})
    _template_section(foreign, PREDEFINED_NAME)['fields'].append(FOREIGN_FIELD)

    return foreign


def _template_section(document: dict[str, Any], name: str) -> dict[str, Any]:
    """A document's section of one template"""
    return next(section for section in document['render_meta']['sections'] if section['name'] == name)


def _drift(payload: dict[str, Any]) -> dict[str, Any]:
    """Rewrites the predefined copy every way it can drift: a label, a field kind, a dropped field, the section label"""
    drifted: dict[str, Any] = deepcopy(payload)
    fields = {field['name']: field for field in drifted['fields']}
    names: list[str] = [field['name'] for field in PREDEFINED_TEMPLATE['fields']]

    fields[names[0]]['label'] = 'HACKED'
    fields[names[1]].update({'type': 'select', 'options': [{'name': 'x', 'label': 'x'}]})
    drifted['fields'] = [field for field in drifted['fields'] if field['name'] != names[2]]

    section = _template_section(drifted, PREDEFINED_NAME)
    section['label'] = 'MY LABEL'
    section['fields'] = names[:2]

    return drifted


def _copy_of(stored: dict[str, Any], template: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The stored type's definitions of the template's fields, and its section of the template"""
    names = [field['name'] for field in template['fields']]
    fields = sorted(
        (field for field in stored['fields'] if field['name'] in names), key=lambda field: names.index(field['name']),
    )

    return fields, _template_section(stored, template['name'])


def _assert_is_the_template(stored: dict[str, Any], template: dict[str, Any]) -> None:
    """The stored copy is exactly the template's"""
    fields, section = _copy_of(stored, template)

    assert fields == template['fields']
    assert (section['label'], section['type']) == (template['label'], template['type'])
    assert section['fields'] == [field['name'] for field in template['fields']]


class TestTheCreate:
    """POST /types/"""

    def test_a_drifted_copy_is_stored_as_the_template(self, rest_api, collections) -> None:
        """Label, kind, the dropped field and the section label all come back"""
        response = rest_api.post(TYPES_URL, json=_drift(_claiming('t30-created', PREDEFINED_TEMPLATE)))

        assert response.status_code == HTTPStatus.CREATED
        _assert_is_the_template(collections['types'].find_one({'name': 't30-created'}), PREDEFINED_TEMPLATE)

    def test_a_faithful_copy_is_stored_as_sent(self, rest_api, collections) -> None:
        """What the frontend builder sends"""
        payload = _claiming('t30-created', PREDEFINED_TEMPLATE, GLOBAL_TEMPLATE)

        assert rest_api.post(TYPES_URL, json=payload).status_code == HTTPStatus.CREATED

        stored = collections['types'].find_one({'name': 't30-created'})
        assert stored['fields'] == payload['fields']
        assert stored['render_meta']['sections'] == payload['render_meta']['sections']

    def test_a_missing_section_is_built(self, rest_api, collections) -> None:
        """The claim alone brings the template's section and fields"""
        payload = _claiming('t30-created')
        payload['global_template_ids'] = [GLOBAL_NAME]

        assert rest_api.post(TYPES_URL, json=payload).status_code == HTTPStatus.CREATED
        _assert_is_the_template(collections['types'].find_one({'name': 't30-created'}), GLOBAL_TEMPLATE)

    def test_a_foreign_field_in_the_template_section_is_a_400(self, rest_api, collections) -> None:
        """Named, and nothing is created"""
        response = rest_api.post(TYPES_URL, json=_with_foreign_field(_claiming('t30-created', PREDEFINED_TEMPLATE)))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TEMPLATE_SECTION_FOREIGN_FIELD_MESSAGE.format(
            template=PREDEFINED_NAME, names=FOREIGN_FIELD,
        )
        assert collections['types'].count_documents({'name': 't30-created'}) == 0

    def test_an_unknown_claim_is_dropped(self, rest_api, collections) -> None:
        """The type is created without claiming it"""
        payload = _claiming('t30-created', PREDEFINED_TEMPLATE)
        payload['global_template_ids'].append(UNKNOWN_TEMPLATE)

        assert rest_api.post(TYPES_URL, json=payload).status_code == HTTPStatus.CREATED
        assert collections['types'].find_one({'name': 't30-created'})['global_template_ids'] == [PREDEFINED_NAME]


class TestTheUpdate:
    """PUT /types/<id>"""

    @staticmethod
    def _stored(rest_api, collections, *templates: dict[str, Any]) -> dict[str, Any]:
        """A type created through the route with faithful copies; its stored document"""
        assert rest_api.post(TYPES_URL, json=_claiming('t30-stored', *templates)).status_code == HTTPStatus.CREATED

        return collections['types'].find_one({'name': 't30-stored'}, {'_id': 0})

    @pytest.mark.parametrize('template', [PREDEFINED_TEMPLATE, GLOBAL_TEMPLATE], ids=['predefined', 'global'])
    def test_a_drifted_copy_is_stored_as_the_template(self, rest_api, collections, template) -> None:
        """A predefined and a non-predefined global template alike"""
        stored = self._stored(rest_api, collections, template)
        payload = deepcopy(stored)
        field = next(f for f in payload['fields'] if f['name'] == template['fields'][0]['name'])
        field['label'] = 'HACKED AGAIN'
        payload.pop('creation_time', None)

        assert rest_api.put(f"{TYPES_URL}{stored['public_id']}", json=payload).status_code == HTTPStatus.ACCEPTED
        _assert_is_the_template(collections['types'].find_one({'name': 't30-stored'}), template)

    def test_a_foreign_field_is_a_400_and_the_type_is_unchanged(self, rest_api, collections) -> None:
        """Nothing is written"""
        stored = self._stored(rest_api, collections, PREDEFINED_TEMPLATE)
        payload = _with_foreign_field(stored)
        payload.pop('creation_time', None)

        response = rest_api.put(f"{TYPES_URL}{stored['public_id']}", json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        _assert_is_the_template(collections['types'].find_one({'name': 't30-stored'}), PREDEFINED_TEMPLATE)

    def test_a_dropped_unknown_claim_keeps_its_section_fields_and_values(self, rest_api, collections) -> None:
        """Not the user removing a template: nothing it named is cleaned up"""
        stored = self._stored(rest_api, collections)
        leftover_section = {'type': 'section', 'name': UNKNOWN_TEMPLATE, 'label': 'Gone', 'fields': [LEFTOVER_FIELD]}
        collections['types'].update_one({'name': 't30-stored'}, {
            '$set': {'global_template_ids': [UNKNOWN_TEMPLATE]},
            '$push': {'fields': {'type': 'text', 'name': LEFTOVER_FIELD, 'label': 'Left over'},
                      'render_meta.sections': leftover_section},
        })
        collections['objects'].insert_one({
            'public_id': STORED_OBJECT_ID, 'type_id': stored['public_id'], 'active': True, 'author_id': 1,
            'version': '1.0.0',
            'fields': [{'name': NAME_FIELD, 'value': 'n'}, {'name': LEFTOVER_FIELD, 'value': 'kept'}],
        })
        payload = collections['types'].find_one({'name': 't30-stored'}, {'_id': 0})
        payload.pop('creation_time', None)

        assert rest_api.put(f"{TYPES_URL}{stored['public_id']}", json=payload).status_code == HTTPStatus.ACCEPTED

        updated = collections['types'].find_one({'name': 't30-stored'})
        assert updated['global_template_ids'] == []
        assert LEFTOVER_FIELD in [field['name'] for field in updated['fields']]
        assert UNKNOWN_TEMPLATE in [section['name'] for section in updated['render_meta']['sections']]
        stored_object = collections['objects'].find_one({'public_id': STORED_OBJECT_ID})
        assert {field['name']: field['value'] for field in stored_object['fields']}[LEFTOVER_FIELD] == 'kept'


class TestTheImport:
    """/import/type/create/"""

    @staticmethod
    def _import(rest_api, entries: list[dict[str, Any]]):
        """Posts an upload of type entries"""
        return rest_api.post(
            IMPORT_CREATE_URL,
            data={'uploadFile': json.dumps(entries, default=str)},
            content_type='multipart/form-data',
        )

    def test_a_drifted_copy_is_imported_as_the_template(self, rest_api, collections) -> None:
        """The template stored HERE wins over the uploaded copy"""
        response = self._import(rest_api, [_drift(_claiming('t30-imported', PREDEFINED_TEMPLATE))])

        assert response.status_code == HTTPStatus.OK
        _assert_is_the_template(collections['types'].find_one({'name': 't30-imported'}), PREDEFINED_TEMPLATE)

    def test_a_foreign_field_refuses_only_its_entry(self, rest_api, collections) -> None:
        """Reported in the partial report; the entry beside it is imported"""
        refused = _with_foreign_field(_claiming('t30-import-refused', PREDEFINED_TEMPLATE))

        response = self._import(rest_api, [refused, _claiming('t30-imported', PREDEFINED_TEMPLATE)])

        errors = [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]
        assert errors == [TypeImportError.FOREIGN_FIELD_IN_TEMPLATE_SECTION.format(
            template=PREDEFINED_NAME, names=[FOREIGN_FIELD],
        )]
        assert collections['types'].count_documents({'name': 't30-import-refused'}) == 0
        assert collections['types'].count_documents({'name': 't30-imported'}) == 1
