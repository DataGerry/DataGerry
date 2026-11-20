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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Functional tests: a global section template update may not leave a target Type of the user sync unusable

Through ``PUT /section_templates/``: making a template field required, without a default, is refused while a target
Type carries the template - the template and the Type stay as they were; the same change with a default value goes
through and reaches the Type; while no target carries it, the change goes through
"""
import json
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType, SectionType
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, UserSyncSettings, write_sync_settings
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/section_templates/'
TEMPLATE_ID: int = 9651
TARGET_TYPE_ID: int = 9652
OTHER_TYPE_ID: int = 9653
TEMPLATE_NAME: str = 'fn-sync-template-badge'
BADGE_FIELD: str = 'fn-sync-badge'
BADGE_DEFAULT: str = 'B-000'
REFUSED_MESSAGE: str = "would then require field(s) the sync cannot always fill"


def _badge(required: bool = False, default: str | None = None) -> dict[str, Any]:
    """The template's one text field"""
    field: dict[str, Any] = {'type': 'text', 'name': BADGE_FIELD, 'label': 'Badge'}

    if required:
        field['required'] = True

    if default is not None:
        field['value'] = default

    return field


def _person_type_using_template(type_id: int) -> dict[str, Any]:
    """A PERSON Type from the blueprint carrying the template's section"""
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, f'fn-sync-template-{type_id}', type_id)
    document['system_type'] = False
    document['fields'].append(_badge())
    document['render_meta']['sections'].append({'type': SectionType.SECTION.value, 'name': TEMPLATE_NAME,
                                                'label': 'Badge', 'fields': [BADGE_FIELD]})
    document['global_template_ids'] = [TEMPLATE_NAME]

    return document


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The global template, the target Type and another PERSON Type using it; the sync targeting TARGET_TYPE_ID"""
    database = database_manager.connector.client[database_name]
    database[CmdbSectionTemplate.COLLECTION].insert_one({
        'public_id': TEMPLATE_ID, 'name': TEMPLATE_NAME, 'label': 'Badge', 'type': SectionType.SECTION.value,
        'is_global': True, 'predefined': False, 'fields': [_badge()],
    })
    database[CmdbType.COLLECTION].insert_many([_person_type_using_template(TARGET_TYPE_ID),
                                               _person_type_using_template(OTHER_TYPE_ID)])
    write_sync_settings(SettingsManager(database_manager, database_name),
                        PersonSyncSettings(users=UserSyncSettings(default_type_id=TARGET_TYPE_ID)))

    yield database

    database[CmdbSectionTemplate.COLLECTION].delete_many({'public_id': TEMPLATE_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [TARGET_TYPE_ID, OTHER_TYPE_ID]}})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)


def _update(rest_api, field: dict[str, Any]) -> Any:
    """Writes the template with the given field"""
    return rest_api.put(ROUTE_URL, query_string={
        'public_id': str(TEMPLATE_ID), 'name': TEMPLATE_NAME, 'label': 'Badge', 'type': SectionType.SECTION.value,
        'is_global': 'true', 'predefined': 'false', 'fields': json.dumps([field]),
    })


def _badge_on(db: Any, collection: str, public_id: int) -> dict[str, Any]:
    """The badge field as the template or the Type stores it"""
    return next(field for field in db[collection].find_one({'public_id': public_id})['fields']
                if field['name'] == BADGE_FIELD)


def test_requiring_the_field_is_refused_while_a_target_carries_it(rest_api, db: Any) -> None:
    """Nothing is written - neither the template nor any Type using it"""
    response = _update(rest_api, _badge(required=True))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert REFUSED_MESSAGE in response.get_json()['message']
    assert str(TARGET_TYPE_ID) in response.get_json()['message']
    assert 'required' not in _badge_on(db, CmdbSectionTemplate.COLLECTION, TEMPLATE_ID)
    assert 'required' not in _badge_on(db, CmdbType.COLLECTION, TARGET_TYPE_ID)
    assert 'required' not in _badge_on(db, CmdbType.COLLECTION, OTHER_TYPE_ID)


def test_with_a_default_value_it_goes_through(rest_api, db: Any) -> None:
    """The create fills it - and the change reaches the target"""
    response = _update(rest_api, _badge(required=True, default=BADGE_DEFAULT))

    assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
    assert _badge_on(db, CmdbType.COLLECTION, TARGET_TYPE_ID).get('required') is True


def test_without_a_target_carrying_it_it_goes_through(rest_api, db: Any, database_manager: MongoDatabaseManager,
                                                      database_name: str) -> None:
    """The sync targets nothing - only the other Type's own business"""
    write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings())

    response = _update(rest_api, _badge(required=True))

    assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
    assert _badge_on(db, CmdbType.COLLECTION, OTHER_TYPE_ID).get('required') is True
