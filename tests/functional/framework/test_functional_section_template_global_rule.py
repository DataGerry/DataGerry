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
Functional tests: a global section template stays global, through the real REST app

  - an update turning a global template non-global is refused with 400; the stored template, its usage count and
    the consuming type's claim are unchanged
  - the frontend's transform (a non-global template made global) is still accepted
  - a transformed template keeps its non-global name, so a demotion passes the name guard - it is refused all the same
"""
import json
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import (
    SectionTemplateKey,
    SectionTemplateUsageKey,
)
from cmdb.models.type_model import CmdbType, SectionType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_templates_constants import (
    GLOBAL_TEMPLATE_DEMOTION_MESSAGE,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/section_templates/'
GLOBAL_ID: int = 93601
LOCAL_ID: int = 93602
TYPE_ID: int = 93601
GLOBAL_NAME: str = 'dg_gst-func-global-rule'
LOCAL_NAME: str = 'section_template-func-global-rule'
GLOBAL_FIELD: str = 'global-rule-field'
LOCAL_FIELD: str = 'local-rule-field'
OWN_FIELD: str = 'global-rule-own'
NAME_KEY: str = SectionTemplateKey.NAME.value
IS_GLOBAL_KEY: str = SectionTemplateKey.IS_GLOBAL.value
CLAIMS_KEY: str = 'global_template_ids'


def _field(name: str) -> dict[str, Any]:
    """A text field definition"""
    return {'type': 'text', 'name': name, 'label': name}


def _template_doc(public_id: int, name: str, field_name: str, is_global: bool) -> dict[str, Any]:
    """A stored, non-predefined template with one field"""
    return {'public_id': public_id, NAME_KEY: name, 'label': name, 'type': SectionType.SECTION.value,
            IS_GLOBAL_KEY: is_global, 'predefined': False, 'fields': [_field(field_name)]}


def _update_body(document: dict[str, Any], is_global: bool) -> dict[str, str]:
    """PUT /section_templates/ parameters sending the stored template back with the given flag"""
    return {'public_id': str(document['public_id']), NAME_KEY: document[NAME_KEY], 'label': document['label'],
            'type': document['type'], IS_GLOBAL_KEY: str(is_global).lower(), 'predefined': 'false',
            'fields': json.dumps(document['fields'])}


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """A global template one type claims and a non-global template nobody claims; purged before and after"""
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        templates.delete_many({'public_id': {'$in': [GLOBAL_ID, LOCAL_ID]}})
        types.delete_many({'public_id': TYPE_ID})

    _purge()
    global_doc: dict[str, Any] = _template_doc(GLOBAL_ID, GLOBAL_NAME, GLOBAL_FIELD, True)
    local_doc: dict[str, Any] = _template_doc(LOCAL_ID, LOCAL_NAME, LOCAL_FIELD, False)
    templates.insert_many([dict(global_doc), dict(local_doc)])
    types.insert_one(make_type_doc(
        TYPE_ID, 'func-global-rule-type', fields=[_field(OWN_FIELD), _field(GLOBAL_FIELD)],
        sections=[{'type': SectionType.SECTION.value, 'name': OWN_FIELD, 'label': 'Own', 'fields': [OWN_FIELD]},
                  {'type': SectionType.SECTION.value, 'name': GLOBAL_NAME, 'label': GLOBAL_NAME,
                   'fields': [GLOBAL_FIELD]}],
        global_template_ids=[GLOBAL_NAME],
    ))

    yield {'templates': templates, 'types': types, 'global': global_doc, 'local': local_doc}
    _purge()


def _usage(rest_api, public_id: int) -> dict[str, Any]:
    """The usage payload of one template"""
    return rest_api.get(f'{ROUTE_URL}{public_id}/count').get_json()


def test_a_global_template_cannot_be_made_non_global(rest_api, seeded: dict[str, Any]) -> None:
    """400; the flag, the usage count and the type's claim stay as they were"""
    usage_before: dict[str, Any] = _usage(rest_api, GLOBAL_ID)

    response = rest_api.put(ROUTE_URL, query_string=_update_body(seeded['global'], False))

    assert (response.status_code, response.get_json()['message']) == (
        HTTPStatus.BAD_REQUEST, GLOBAL_TEMPLATE_DEMOTION_MESSAGE)
    assert seeded['templates'].find_one({'public_id': GLOBAL_ID})[IS_GLOBAL_KEY] is True
    assert usage_before[SectionTemplateUsageKey.TYPES] == 1
    assert _usage(rest_api, GLOBAL_ID) == usage_before
    assert seeded['types'].find_one({'public_id': TYPE_ID})[CLAIMS_KEY] == [GLOBAL_NAME]


def test_a_non_global_template_can_be_made_global(rest_api, seeded: dict[str, Any]) -> None:
    """The frontend's transform action keeps working"""
    response = rest_api.put(ROUTE_URL, query_string=_update_body(seeded['local'], True))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert seeded['templates'].find_one({'public_id': LOCAL_ID})[IS_GLOBAL_KEY] is True


def test_a_transformed_template_cannot_be_made_non_global_again(rest_api, seeded: dict[str, Any]) -> None:
    """Its name never changed, so only the flag rule stops the demotion"""
    assert rest_api.put(ROUTE_URL, query_string=_update_body(seeded['local'], True)).status_code == HTTPStatus.ACCEPTED

    response = rest_api.put(ROUTE_URL, query_string=_update_body(seeded['local'], False))

    assert (response.status_code, response.get_json()['message']) == (
        HTTPStatus.BAD_REQUEST, GLOBAL_TEMPLATE_DEMOTION_MESSAGE)
    assert seeded['templates'].find_one({'public_id': LOCAL_ID})[IS_GLOBAL_KEY] is True
