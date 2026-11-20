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
Functional tests: a person needs a display name, not a first or last name

The PERSON Type is built from the current schema. ``POST /objects`` stores a person carrying only its display name;
one without a display name is still refused with the required-field 400
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.framework.person_types.default_person_types import build_default_person_type
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'
PERSON_TYPE_ID: int = 9491
PERSON_TYPE_NAME: str = 'fn-optional-names-person'
PERSON_ID: int = 9492
DISPLAY_NAME: str = 'svc-backup'
AUTHOR_ID: int = 1
MISSING_VALUE_MESSAGE: str = 'Missing value for required field(s)'


@pytest.fixture(name='person_type', autouse=True)
def fixture_person_type(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A PERSON Type built from the current schema; it, the person and the logs go afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    document: dict[str, Any] = build_default_person_type(SpecialType.PERSON, PERSON_TYPE_NAME, PERSON_TYPE_ID)
    document['system_type'] = False
    types.insert_one(document)

    yield

    types.delete_one({'public_id': PERSON_TYPE_ID})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many({'public_id': PERSON_ID})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many({'object_id': PERSON_ID})


def _person(fields: dict[str, str]) -> dict[str, Any]:
    """A create body for the person, carrying the given field values"""
    return {
        'public_id': PERSON_ID,
        'type_id': PERSON_TYPE_ID,
        'author_id': AUTHOR_ID,
        'active': True,
        'fields': [{'name': name, 'value': value, 'type': 'text'} for name, value in fields.items()],
    }


def test_a_person_with_only_a_display_name_is_stored(rest_api, database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
    """First and last name may stay empty - a user mirrored by the sync may carry neither"""
    response = rest_api.post(f'{ROUTE_URL}/', json=_person({PersonField.DISPLAY_NAME.value: DISPLAY_NAME}))

    assert response.status_code == HTTPStatus.OK
    stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': PERSON_ID})
    assert stored is not None


def test_a_person_without_a_display_name_is_refused(rest_api, database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
    """The display name stays required"""
    response = rest_api.post(f'{ROUTE_URL}/', json=_person({PersonField.FIRST_NAME.value: 'Ann',
                                                            PersonField.LAST_NAME.value: 'Lee'}))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert MISSING_VALUE_MESSAGE in response.get_json()['message']
    assert database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
        {'public_id': PERSON_ID}) is None
