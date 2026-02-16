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
Bulk change objects - Tests
"""
from logging import Logger, getLogger
import copy
from datetime import datetime, timezone
from http import HTTPStatus

from pymongo.mongo_client import MongoClient
from pymongo.collection import Collection
from pytest import fixture

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import (
    CmdbType,
    TypeFieldSection,
    TypeSummary,
    TypeRenderMeta,
)

from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.group_acl import GroupACL
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

@fixture(scope='module', name="example_type")
def fixture_example_type():
    """
    Provides an example CMDB Type fixture for testing.
    Returns a CmdbType instance with predefined fields, sections, and ACL settings.
    """
    return CmdbType(
        public_id=1,
        name='test',
        label='Test',
        author_id=1,
        creation_time=datetime.now(),
        active=True,
        version=None,
        description='Test type',
        render_meta=TypeRenderMeta(
            sections=[
                TypeFieldSection(type='section', name='test-section',
                                 label='TEST', fields=['dummy-field-1', 'dummy-field-2'])
            ],
            summary=TypeSummary(fields=['dummy-field-1'])
        ),
        fields=[{
            "type": "text",
            "name": "dummy-field-1",
            "label": "Test"
        }, {
            "type": "text",
            "name": "dummy-field-2",
            "label": "Test"
        }],
        acl=AccessControlList(activated=False, groups=GroupACL(includes=None))
    )


@fixture(scope='module', name="example_object")
def fixture_example_object():
    """
    Provides an example CMDB Object fixture for testing.
    Returns a CmdbObject instance with predefined fields and attributes.
    """
    return CmdbObject(
        public_id=1,
        type_id=1,
        status=True,
        creation_time=datetime.now(timezone.utc),
        author_id=1,
        active=True,
        fields=[
            {
                "name": "dummy-field-1",
                "value": 'dummy-value'
            },
            {
                "name": "dummy-field-2",
                "value": ''
            }
        ],
        version='1.0.0'
    )


@fixture(scope='module', name="change_object")
def fixture_change_object() -> dict:
    """
    Provides a sample object change request payload.
    Ensures 'active' property remains undefined for schema validation.
    """
    return {
        "type_id": 1,
        "version": "1.0.1",
        "author_id": 1,
        "fields": [
            {
                "name": "dummy-field-2",
                "value": "dummy-change"
            }
        ]
    }


@fixture(scope='module', name="collection")
def fixture_collection(connector, database_name):
    """
    Provides a MongoDB collection fixture for CMDB Types
    """
    client: MongoClient = connector.client
    collection: Collection = client.get_database(database_name).get_collection(CmdbType.COLLECTION)

    return collection


@fixture(scope='module', autouse=True)
def setup(request, collection, example_type):
    """
    Setup fixture to insert example CMDB Type into the database.
    Cleans up the collection after tests run.
    """
    collection.insert_one(document=CmdbType.to_json(example_type))

    def drop_collection():
        collection.drop()

    request.addfinalizer(drop_collection)

class TestBulkChangeFrameworkObjects:
    """
    Test suite for bulk object modification in CMDB.
    Includes tests for inserting objects, modifying field values, and changing active states.
    """
    OBJECT_COLLECTION: str = CmdbObject.COLLECTION
    ROUTE_URL: str = '/objects'

    def test_insert_object(self, rest_api, example_object, full_access_user):
        """
        Tests insertion of multiple CMDB objects.
        Ensures objects are inserted successfully and can be retrieved.
        """
        i = 0
        while i < 3:
            i = i + 1
            data = copy.copy(CmdbObject.to_json(example_object))
            data['public_id'] = i
            data['active'] = i % 2 != 0
            data['fields'][0]['value'] = f'dummy-value-{i}'
            access_insert_types_response = rest_api.post(f'{self.ROUTE_URL}/', json=data, user=full_access_user)
            assert access_insert_types_response.status_code != (HTTPStatus.FORBIDDEN or HTTPStatus.UNAUTHORIZED)

        assert len(rest_api.get(f'{self.ROUTE_URL}/').get_json()['results']) == 3


    def test_bulk_change_object_field_value(self, rest_api, change_object, full_access_user):
        """
        Tests bulk modification of CMDB object field values.
        Ensures updated values persist correctly across multiple objects.
        """
        expectations = rest_api.get(f'{self.ROUTE_URL}/').get_json()['results']
        params = {'objectIDs': [1, 2, 3]}

        response = rest_api.put(f'{self.ROUTE_URL}/0', json=change_object, query_string=params, user=full_access_user)
        results: list[dict] = response.get_json()['results']

        assert response.status_code == HTTPStatus.ACCEPTED
        assert len(expectations) == len(results)

        # Compare all field values with the change object
        assert change_object['fields'][0] == results[0]['fields'][1]
        assert change_object['fields'][0] == results[1]['fields'][1]
        assert change_object['fields'][0] == results[2]['fields'][1]

        # Compare all field values with the original
        assert results[0]['fields'] != expectations[0]['fields']
        assert results[1]['fields'] != expectations[1]['fields']
        assert results[2]['fields'] != expectations[2]['fields']

        # Compare active state
        assert results[0]['active'] == expectations[0]['active']
        assert results[1]['active'] == expectations[1]['active']
        assert results[2]['active'] == expectations[2]['active']


    def test_bulk_change_object_active_state(self, rest_api, change_object, full_access_user):
        """
        Tests bulk modification of CMDB object field values.
        Ensures updated values persist correctly across multiple objects.
        """
        expectations = rest_api.get(f'{self.ROUTE_URL}/').get_json()['results']
        params = {'objectIDs': [1, 2, 3]}

        change_object['active'] = True
        response = rest_api.put(f'{self.ROUTE_URL}/0', json=change_object, query_string=params, user=full_access_user)
        results: list[dict] = response.get_json()['results']

        assert response.status_code == HTTPStatus.ACCEPTED
        assert len(expectations) == len(results)

        # Compare active state
        assert results[0]['active']
        assert results[1]['active']
        assert results[2]['active']
