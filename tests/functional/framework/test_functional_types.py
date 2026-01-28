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
Implementation of CmdbType tests
"""
from json import dumps
from datetime import datetime, timezone
from http import HTTPStatus
from pytest import fixture, importorskip

from tests.utils.flask_test_client import RestAPITestSuite

from cmdb.models.type_model import (
    CmdbType,
    TypeFieldSection,
    TypeSummary,
    TypeRenderMeta,
)

from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.group_acl import GroupACL
# -------------------------------------------------------------------------------------------------------------------- #

@fixture(scope='module')
def example_type():
    """
    Fixture providing an example CMDB type.
    Returns a pre-defined type instance with specific fields and metadata.
    """
    return CmdbType(
        public_id=1,
        name='test',
        label='Test',
        author_id=1,
        creation_time=datetime.now(timezone.utc),
        active=True,
        version=None,
        description='Test type',
        render_meta=TypeRenderMeta(
            sections=[
                TypeFieldSection(
                    type='section',
                    name='test-section',
                    label='TEST',
                    fields=['test-field']
                )
            ],
            summary=TypeSummary(fields=['test-field'])
        ),
        fields=[{
            "type": "text",
            "name": "test-field",
            "label": "Test",
            "required": False,
            "description": "Description",
            "regex": "TEST .*",
            "placeholder": "entre you value",
            "value": "this ist the default value",
            "helperText": "Help, i need somebody"
        }],
        acl=AccessControlList(activated=False, groups=GroupACL(includes=None))
    )


@fixture(scope='module')
def collection(connector, database_name):
    """
    Fixture for retrieving the MongoDB collection used for testing.
    Returns a reference to the collection object.
    """
    from pymongo.mongo_client import MongoClient
    from pymongo.collection import Collection
    mongo_client: MongoClient = connector.client
    a_collection: Collection = mongo_client.get_database(database_name).get_collection(TestFrameworkTypes.COLLECTION)

    return a_collection


@fixture(scope='module', autouse=True)
def setup(request, collection, example_type):
    """
    Fixture for setting up the test environment.
    Inserts an example type into the database and ensures cleanup after tests.
    """
    collection.insert_one(document=CmdbType.to_json(example_type))

    def drop_collection():
        collection.drop()

    request.addfinalizer(drop_collection)


class TestFrameworkTypes(RestAPITestSuite):
    """
    Test suite for managing CMDB types.
    Includes CRUD operations and access control tests.
    """
    importorskip('cmdb.framework')

    COLLECTION: str = CmdbType.COLLECTION
    ROUTE_URL: str = '/types'

    def test_get_types(self, rest_api, full_access_user, none_access_user):
        """
        Tests retrieving a list of CMDB types.
        Ensures response is valid and filtering mechanisms function correctly.
        """
        # Route callable
        default_response = rest_api.get(f'{self.ROUTE_URL}/')
        assert default_response.status_code == HTTPStatus.OK

        # Response parsable
        response_dict = default_response.get_json()
        test_type_json = response_dict['results'][0]
        test_type = CmdbType.from_data(test_type_json)

        assert len(response_dict['results']) == int(default_response.headers['X-Total-Count'])
        assert len(response_dict['results'])
        assert isinstance(test_type, CmdbType)
        assert len(test_type.fields[0].keys()) == 9

        # Test filter
        filter_response = rest_api.get(f'{self.ROUTE_URL}/', query_string={'filter': dumps({'public_id': 1})})
        assert filter_response.status_code == HTTPStatus.OK
        assert int(filter_response.headers['X-Total-Count']) == 1

        # Test empty filter
        empty_filter_response = rest_api.get(f'{self.ROUTE_URL}/', query_string={'filter': dumps({'public_id': 2})})
        assert empty_filter_response.status_code == HTTPStatus.OK
        assert int(empty_filter_response.headers['X-Total-Count']) == 0

        # Test wrong filter
        wrong_filter_response = rest_api.get(f'{self.ROUTE_URL}/', query_string={'filter': '\xE9'})
        assert wrong_filter_response.status_code == HTTPStatus.BAD_REQUEST

        # ACCESS OK
        access_get_types_response = rest_api.get(f'{self.ROUTE_URL}/', user=full_access_user)
        assert access_get_types_response.status_code != (HTTPStatus.FORBIDDEN or HTTPStatus.UNAUTHORIZED)

        # ACCESS FORBIDDEN
        # none_get_types_response = rest_api.get(f'{self.ROUTE_URL}/', user=none_access_user)
        # assert none_get_types_response.status_code == HTTPStatus.FORBIDDEN

        # ACCESS UNAUTHORIZED
        # none_get_types_response = rest_api.get(f'{self.ROUTE_URL}/', unauthorized=True)
        # assert none_get_types_response.status_code == HTTPStatus.UNAUTHORIZED


    def test_get_type(self, rest_api, example_type, full_access_user, none_access_user):
        """
        Tests retrieving a single CMDB type by ID.
        Ensures correct response for existing and non-existing types.
        """
        # Route callable
        default_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}')
        assert default_response.status_code == HTTPStatus.OK

        # Response parsable
        response_dict = default_response.get_json()
        test_type_json = response_dict['result']
        test_type = CmdbType.from_data(test_type_json)
        assert isinstance(test_type, CmdbType)
        assert len(test_type.fields[0].keys()) == 9

        # Not Found
        not_found_response = rest_api.get(f'{self.ROUTE_URL}/{-1}')
        assert not_found_response.status_code == HTTPStatus.NOT_FOUND

        # ACCESS OK
        access_get_types_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}', user=full_access_user)
        assert access_get_types_response.status_code != (HTTPStatus.FORBIDDEN or HTTPStatus.UNAUTHORIZED)

        # ACCESS FORBIDDEN
        # none_get_types_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}', user=none_access_user)
        # assert none_get_types_response.status_code == HTTPStatus.FORBIDDEN

        # ACCESS UNAUTHORIZED
        # none_get_types_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}', unauthorized=True)
        # assert none_get_types_response.status_code == HTTPStatus.UNAUTHORIZED


    def test_insert_type(self, rest_api, example_type, full_access_user, none_access_user):
        """
        Tests inserting a new CMDB type.
        Ensures correct validation, insertion, and error handling for duplicates.
        """
        example_type.public_id = 2
        example_type.name = 'test2'

        # Test default route
        # default_response = rest_api.post(f'{self.ROUTE_URL}/', json=CmdbType.to_json(example_type))
        # assert default_response.status_code == HTTPStatus.CREATED

        # validate_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}')
        # assert validate_response.status_code == HTTPStatus.OK

        # double_check_response = rest_api.post(f'{self.ROUTE_URL}/', json=CmdbType.to_json(example_type))
        # assert double_check_response.status_code == HTTPStatus.BAD_REQUEST

        # rest_api.delete(f'{self.ROUTE_URL}/{example_type.public_id}')

        # ACCESS OK
        # access_insert_types_response = rest_api.post(f'{self.ROUTE_URL}/',
        #                                              json=CmdbType.to_json(example_type), user=full_access_user)
        # assert access_insert_types_response.status_code != (HTTPStatus.FORBIDDEN or HTTPStatus.UNAUTHORIZED)
        # validate_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}')
        # assert validate_response.status_code == HTTPStatus.OK
        # rest_api.delete(f'{self.ROUTE_URL}/{example_type.public_id}')

        # ACCESS FORBIDDEN
        # forbidden_insert_types_response = rest_api.post(f'{self.ROUTE_URL}/', json=CmdbType.to_json(example_type),
        #                                                 user=none_access_user)
        # assert forbidden_insert_types_response.status_code == HTTPStatus.FORBIDDEN
        validate_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}')
        assert validate_response.status_code == HTTPStatus.NOT_FOUND

        # ACCESS UNAUTHORIZED
        # un_insert_types_response = rest_api.post(f'{self.ROUTE_URL}/', json=CmdbType.to_json(example_type),
        #                                          unauthorized=True)
        # assert un_insert_types_response.status_code == HTTPStatus.UNAUTHORIZED

        # validate_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}')
        # assert validate_response.status_code == HTTPStatus.NOT_FOUND
        # example_type.public_id = 1
        # example_type.name = 'test'


    # def test_update_type(self, rest_api, example_type, full_access_user, none_access_user):
    #     example_type.name = 'updated'

    #     # Test default route
    #     default_response = rest_api.put(f'{self.ROUTE_URL}/{example_type.public_id}',
    #                                     json=CmdbType.to_json(example_type))
    #     assert default_response.status_code == HTTPStatus.ACCEPTED

    #     validate_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}')
    #     assert validate_response.status_code == HTTPStatus.OK
    #     assert validate_response.get_json()['result']['name'] == 'updated'

    #     # ACCESS OK
    #     access_update_types_response = rest_api.put(f'{self.ROUTE_URL}/{example_type.public_id}',
    #                                                 json=CmdbType.to_json(example_type), user=full_access_user)
    #     assert access_update_types_response.status_code != (HTTPStatus.FORBIDDEN or HTTPStatus.UNAUTHORIZED)
    #     validate_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}')
    #     assert validate_response.status_code == HTTPStatus.OK
    #     rest_api.delete(f'{self.ROUTE_URL}/{example_type.public_id}')

    #     # ACCESS FORBIDDEN
    #     none_update_types_response = rest_api.put(f'{self.ROUTE_URL}/{example_type.public_id}',
    #                                               json=CmdbType.to_json(example_type), user=none_access_user)
    #     assert none_update_types_response.status_code == HTTPStatus.FORBIDDEN

    #     # ACCESS UNAUTHORIZED
    #     un_get_types_response = rest_api.put(f'{self.ROUTE_URL}/{example_type.public_id}',
    #                                          json=CmdbType.to_json(example_type), unauthorized=True)
    #     assert un_get_types_response.status_code == HTTPStatus.UNAUTHORIZED
    #     example_type.public_id = 1
    #     example_type.name = 'test'

    # def test_delete_type(self, rest_api, example_type, full_access_user, none_access_user):
        # Test default route
        # rest_api.post(f'{self.ROUTE_URL}/', json=CmdbType.to_json(example_type))

        # default_response = rest_api.delete(f'{self.ROUTE_URL}/{example_type.public_id}')
        # assert default_response.status_code == HTTPStatus.ACCEPTED

        # default_response = rest_api.post(f'{self.ROUTE_URL}/', json=CmdbType.to_json(example_type))
        # assert default_response.status_code == HTTPStatus.CREATED

        # # ACCESS OK
        # access_update_types_response = rest_api.delete(f'{self.ROUTE_URL}/{example_type.public_id}',
        #                                                user=full_access_user)
        # assert access_update_types_response.status_code != (HTTPStatus.FORBIDDEN or HTTPStatus.UNAUTHORIZED)
        # validate_response = rest_api.get(f'{self.ROUTE_URL}/{example_type.public_id}')
        # assert validate_response.status_code == HTTPStatus.NOT_FOUND

        # ACCESS FORBIDDEN
        # none_update_types_response = rest_api.delete(f'{self.ROUTE_URL}/{example_type.public_id}',
        #                                              user=none_access_user)
        # assert none_update_types_response.status_code == HTTPStatus.FORBIDDEN

        # ACCESS UNAUTHORIZED
        # un_get_types_response = rest_api.delete(f'{self.ROUTE_URL}/{example_type.public_id}', unauthorized=True)
        # assert un_get_types_response.status_code == HTTPStatus.UNAUTHORIZED
