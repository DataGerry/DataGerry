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
Functional tests: a Type update keeps the stored ``active`` and ``selectable_as_parent`` when the body leaves them out

Measured before: both flags carried a create default (True) into the update - the write schema's ``default`` on
``PUT /types/<id>``, ``normalize_boolean_flags`` on the type import's update - so an update of an inactive Type that
did not send ``active`` switched it back on, and every Object write of the Type with it. Now an omitted flag keeps
the stored value on both paths; a sent flag still replaces it. The type builder always sends both, so its requests
behave as before
"""
import json
from http import HTTPStatus
from typing import Any, Iterator

import pytest
from pymongo.collection import Collection

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_URL: str = '/types'
IMPORT_UPDATE_URL: str = '/import/type/update/'
UPLOAD_FIELD: str = 'uploadFile'
MULTIPART: str = 'multipart/form-data'

TYPE_ID: int = 47961
TYPE_NAME: str = 'type-kept-flags'
EDITED_LABEL: str = 'type-kept-flags-edited'

ACTIVE: str = TypeSchemaKey.ACTIVE.value
SELECTABLE: str = TypeSchemaKey.SELECTABLE_AS_PARENT.value
# The audit keys are the server's; a datetime would not survive the JSON body either
SERVER_KEYS: tuple[str, ...] = ('author_id', 'creation_time')
# How the type import spells "empty" - the create default fills it in
EMPTY_IMPORT_VALUES: list[Any] = [None, '']


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Collection]:
    """An inactive Type that is not selectable as a parent - removed again after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    types.insert_one({**make_type_doc(TYPE_ID, TYPE_NAME), ACTIVE: False, SELECTABLE: False})
    yield types
    types.delete_many({'public_id': TYPE_ID})


def _body(**flags: Any) -> dict[str, Any]:
    """The Type as an update sends it: a new label, the flags only when a test adds them"""
    body: dict[str, Any] = {key: value for key, value in make_type_doc(TYPE_ID, TYPE_NAME).items()
                            if key not in SERVER_KEYS and key != ACTIVE}
    body['label'] = EDITED_LABEL

    return {**body, **flags}


def _entry(**flags: Any) -> dict[str, Any]:
    """The Type as an import file carries it (the audit keys included): a new label, the flags only when added"""
    entry: dict[str, Any] = {key: value for key, value in make_type_doc(TYPE_ID, TYPE_NAME).items() if key != ACTIVE}
    entry['label'] = EDITED_LABEL

    return {**entry, **flags}


def _stored(types: Collection) -> dict[str, Any]:
    """The Type as stored"""
    return types.find_one({'public_id': TYPE_ID})


def _put(rest_api, body: dict[str, Any]) -> None:
    """PUT /types/<id>, asserted accepted"""
    response = rest_api.put(f'{TYPES_URL}/{TYPE_ID}', json=body)

    assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()


def _import_update(rest_api, entry: dict[str, Any]) -> None:
    """POST /import/type/update/ with one entry, asserted imported"""
    response = rest_api.post(IMPORT_UPDATE_URL, data={UPLOAD_FIELD: json.dumps([entry], default=str)},
                             content_type=MULTIPART)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['failed_imports'] == []


class TestTheUpdateRoute:
    """PUT /types/<id>"""

    def test_an_omitted_active_keeps_an_inactive_type_inactive(self, rest_api, types: Collection) -> None:
        """Before: the body without ``active`` switched the Type back on"""
        _put(rest_api, _body())

        stored = _stored(types)
        assert stored['label'] == EDITED_LABEL
        assert stored[ACTIVE] is False

    def test_an_omitted_selectable_as_parent_keeps_the_stored_value(self, rest_api, types: Collection) -> None:
        """Before: it became True"""
        _put(rest_api, _body())

        assert _stored(types)[SELECTABLE] is False

    def test_a_sent_flag_still_replaces_the_stored_one(self, rest_api, types: Collection) -> None:
        """The type builder's request: both flags sent"""
        _put(rest_api, _body(**{ACTIVE: True, SELECTABLE: True}))

        stored = _stored(types)
        assert stored[ACTIVE] is True
        assert stored[SELECTABLE] is True

    def test_a_null_flag_is_still_refused(self, rest_api, types: Collection) -> None:
        """Only leaving the key out keeps the stored value; the schema refuses a null as before"""
        response = rest_api.put(f'{TYPES_URL}/{TYPE_ID}', json=_body(**{ACTIVE: None}))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(types)[ACTIVE] is False

    def test_a_create_still_starts_active_and_selectable(self, rest_api, database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """The defaults stay on the create"""
        created_name: str = f'{TYPE_NAME}-created'
        body: dict[str, Any] = {**_body(), 'name': created_name}
        body.pop(SELECTABLE, None)
        body.pop('public_id', None)
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

        try:
            response = rest_api.post(f'{TYPES_URL}/', json=body)

            assert response.status_code == HTTPStatus.CREATED, response.get_json()
            stored = types.find_one({'name': created_name})
            assert stored[ACTIVE] is True
            assert stored[SELECTABLE] is True
        finally:
            types.delete_many({'name': created_name})


class TestTheImportUpdate:
    """POST /import/type/update/"""

    def test_an_omitted_flag_keeps_the_stored_value(self, rest_api, types: Collection) -> None:
        """Before: both became True"""
        _import_update(rest_api, _entry())

        stored = _stored(types)
        assert stored['label'] == EDITED_LABEL
        assert stored[ACTIVE] is False
        assert stored[SELECTABLE] is False

    @pytest.mark.parametrize('empty', EMPTY_IMPORT_VALUES, ids=['null', 'empty-string'])
    def test_an_empty_flag_keeps_the_stored_value(self, rest_api, types: Collection, empty: Any) -> None:
        """The import's "empty" is an omission, as on the create"""
        _import_update(rest_api, _entry(**{ACTIVE: empty, SELECTABLE: empty}))

        stored = _stored(types)
        assert stored[ACTIVE] is False
        assert stored[SELECTABLE] is False

    def test_a_sent_flag_still_replaces_the_stored_one(self, rest_api, types: Collection) -> None:
        """Including the import's lenient spellings"""
        _import_update(rest_api, _entry(**{ACTIVE: 'yes', SELECTABLE: True}))

        stored = _stored(types)
        assert stored[ACTIVE] is True
        assert stored[SELECTABLE] is True
