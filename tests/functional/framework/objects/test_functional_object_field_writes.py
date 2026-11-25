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
Functional tests: an object write must be allowed to write every field it changes, through the real REST app

A role granting create / edit without ``write_regular_fields`` writes no field: a create filling one, a PUT or a bulk
PATCH changing one, and an import row are refused, naming the fields (403 on the routes, a failed row in the import
report); a PUT sending everything back unchanged passes. A role that writes regular fields passes them all
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from io import BytesIO
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_engine import FIELDS_REFUSED_MESSAGE
from cmdb.interface.rest_api.routes.importer_routes.importer_constants import ImporterRight
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
IMPORT_URL: str = '/import/object/'
TYPE_ID: int = 97461
STORED_ID: int = 97462
NO_WRITE_GROUP_ID: int = 97463
WRITE_GROUP_ID: int = 97464
NO_WRITE_USER_ID: int = 97465
WRITE_USER_ID: int = 97466
HOST: str = 'host'
STORED_HOST: str = 'stored-host'
NEW_HOST: str = 'new-host'
RIGHTS: list[str] = [TypeRight.VIEW.value, ObjectRightName.VIEW.value, ObjectRightName.ADD.value,
                     ObjectRightName.EDIT.value, ImporterRight.OBJECT.value]
REFUSED: str = FIELDS_REFUSED_MESSAGE.format(names=[HOST], type_id=TYPE_ID)


def _type_doc() -> dict[str, Any]:
    """A type with one text field"""
    return {
        'public_id': TYPE_ID, 'name': f'field-writes-{TYPE_ID}', 'label': 'Field writes', 'author_id': 1,
        'active': True, 'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
        'fields': [{'type': 'text', 'name': HOST, 'label': HOST}],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'summary': {'fields': [HOST]},
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [HOST]}]},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _role(public_id: int, write_regular_fields: bool) -> dict[str, Any]:
    """A role viewing, creating and editing the type"""
    return {'public_id': public_id, 'name': f'field-writes-{public_id}', 'description': '', 'types': [TYPE_ID],
            'operations': ['view', 'create', 'edit'], 'write_regular_fields': write_regular_fields,
            'field_classes': []}


def _body(host: str) -> dict[str, Any]:
    """An object of the type"""
    return {'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': HOST, 'value': host}]}


def _user(public_id: int, group_id: int) -> CmdbUser:
    """A writer"""
    return CmdbUser(public_id=public_id, user_name=f'field-writes-{public_id}', active=True, group_ids=[group_id])


NO_WRITER: CmdbUser = _user(NO_WRITE_USER_ID, NO_WRITE_GROUP_ID)
WRITER: CmdbUser = _user(WRITE_USER_ID, WRITE_GROUP_ID)


@pytest.fixture(name='objects', autouse=True)
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The type, one stored object, two groups with the object rights - one role writes fields, one does not"""
    database = database_manager.connector.client[database_name]
    objects = database[CmdbObject.COLLECTION]
    database[CmdbType.COLLECTION].insert_one(_type_doc())
    objects.insert_one({**_body(STORED_HOST), 'public_id': STORED_ID, 'creation_time': datetime.now(timezone.utc)})
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': group_id, 'name': f'field-writes-{group_id}', 'label': 'G', 'rights': RIGHTS}
        for group_id in (NO_WRITE_GROUP_ID, WRITE_GROUP_ID)])
    database[CmdbUser.COLLECTION].insert_many([
        {'public_id': user.public_id, 'user_name': user.user_name, 'active': True, 'group_ids': user.group_ids,
         'registration_time': datetime.now(timezone.utc)} for user in (NO_WRITER, WRITER)])
    database[CmdbScopeRole.COLLECTION].insert_many([_role(97471, False), _role(97472, True)])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': 97473, 'group_id': NO_WRITE_GROUP_ID, 'role_id': 97471, 'scope': '*'},
        {'public_id': 97474, 'group_id': WRITE_GROUP_ID, 'role_id': 97472, 'scope': '*'},
    ])

    yield objects

    database[CmdbType.COLLECTION].delete_one({'public_id': TYPE_ID})
    objects.delete_many({'type_id': TYPE_ID})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [NO_WRITE_GROUP_ID, WRITE_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': [NO_WRITE_USER_ID, WRITE_USER_ID]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _refusal(response: Any) -> tuple[int, str]:
    """Status and message"""
    return response.status_code, response.get_json()['message']


class TestCreate:
    """POST /objects/"""

    def test_a_filled_field_the_role_may_not_write_is_refused(self, rest_api) -> None:
        """403 naming the field"""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_body(NEW_HOST), user=NO_WRITER)

        assert _refusal(response) == (HTTPStatus.FORBIDDEN, REFUSED)

    def test_a_writing_role_creates(self, rest_api, objects: Any) -> None:
        """Created - the route's own 200"""
        assert rest_api.post(f'{OBJECTS_URL}/', json=_body(NEW_HOST), user=WRITER).status_code == HTTPStatus.OK
        assert objects.count_documents({'type_id': TYPE_ID}) == 2


class TestEdit:
    """PUT /objects/<id> and PATCH /objects/?objectIDs="""

    def test_a_changed_field_is_refused(self, rest_api, objects: Any) -> None:
        """403 naming it; the stored value stays"""
        response = rest_api.put(f'{OBJECTS_URL}/{STORED_ID}', json=_body(NEW_HOST), user=NO_WRITER)

        assert _refusal(response) == (HTTPStatus.FORBIDDEN, REFUSED)
        assert objects.find_one({'public_id': STORED_ID})['fields'][0]['value'] == STORED_HOST

    def test_an_unchanged_form_passes(self, rest_api) -> None:
        """Every field sent back as stored - nothing written"""
        response = rest_api.put(f'{OBJECTS_URL}/{STORED_ID}', json=_body(STORED_HOST), user=NO_WRITER)

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_a_writing_role_edits(self, rest_api) -> None:
        """202"""
        response = rest_api.put(f'{OBJECTS_URL}/{STORED_ID}', json=_body(NEW_HOST), user=WRITER)

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_a_bulk_patch_changing_a_field_is_refused(self, rest_api, objects: Any) -> None:
        """The same rule on the bulk path"""
        response = rest_api.patch(f'{OBJECTS_URL}/', json={'fields': [{'name': HOST, 'value': NEW_HOST}]},
                                  query_string={'objectIDs': [STORED_ID]}, user=NO_WRITER)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert objects.find_one({'public_id': STORED_ID})['fields'][0]['value'] == STORED_HOST


def _import(rest_api: Any, user: CmdbUser, overwrite: bool = False) -> Any:
    """Imports one CSV row into the type - a new object, or with ``overwrite`` the stored one under its id"""
    mapping: list[dict[str, Any]] = [{'name': HOST, 'value': 0, 'type': 'field'}]
    body: str = f'{HOST}\n{NEW_HOST}\n'
    config: dict[str, Any] = {'type_id': TYPE_ID, 'mapping': mapping}

    if overwrite:
        body = f'public_id,{HOST}\n{STORED_ID},{NEW_HOST}\n'
        config = {'type_id': TYPE_ID, 'overwrite_public': True,
                  'mapping': [{'name': 'public_id', 'value': 0, 'type': 'property'},
                              {'name': HOST, 'value': 1, 'type': 'field'}]}

    form = {'file': (BytesIO(body.encode('utf-8')), 'import.csv'), 'file_format': 'csv',
            'parser_config': json.dumps({}), 'importer_config': json.dumps(config)}

    return rest_api.post(IMPORT_URL, data=form, content_type='multipart/form-data', user=user)


def _import_errors(response: Any) -> list[str]:
    """Every error of every failed row"""
    return [error for failure in response.get_json()['failed_imports'] for error in failure['errors']]


class TestImport:
    """POST /import/object/"""

    def test_a_row_the_role_may_not_write_fails(self, rest_api, objects: Any) -> None:
        """The row is reported failed with the refusal; nothing is written"""
        assert _import_errors(_import(rest_api, NO_WRITER)) == [REFUSED]
        assert objects.count_documents({'type_id': TYPE_ID}) == 1

    def test_an_overwrite_changing_a_field_fails(self, rest_api, objects: Any) -> None:
        """Judged as an edit of the stored object; the stored value stays"""
        assert _import_errors(_import(rest_api, NO_WRITER, overwrite=True)) == [REFUSED]
        assert objects.find_one({'public_id': STORED_ID})['fields'][0]['value'] == STORED_HOST

    def test_a_writing_role_overwrites(self, rest_api, objects: Any) -> None:
        """The stored object takes the row"""
        assert not _import_errors(_import(rest_api, WRITER, overwrite=True))
        assert objects.find_one({'public_id': STORED_ID})['fields'][0]['value'] == NEW_HOST

    def test_a_writing_role_imports(self, rest_api, objects: Any) -> None:
        """No failure; the object stored"""
        response = _import(rest_api, WRITER)

        assert response.get_json()['failed_imports'] == []
        assert objects.count_documents({'type_id': TYPE_ID}) == 2
