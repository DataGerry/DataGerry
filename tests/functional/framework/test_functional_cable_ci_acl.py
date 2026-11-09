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
Functional tests for a Cable CI the caller may not READ, on every route that shows a connection's cable

The connection rights govern the link (Q13): who may read, create and change a connection. A Cable CI's values -
name, type, length, colour, description - are an object's contents, and follow the CI's type ACL. Measured before:
with READ on the Cable type denied, `GET /objects/<ci>` answered 403 while every connection read, the ports overview,
both cabling views, the CI Explorer's physical edge and the write answers showed the CI's values, and the cable
picker listed it. Now the block keeps `cable_ci_id` and says `restricted: true`, with no value, and the picker does
not offer the cable; a caller who may read the type sees everything as before.

The seeded types, objects and ports are those of the connection route tests, reused by their fixtures
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.port_connection_model import CableViewKey
from cmdb.models.type_model import CmdbType
from tests.functional.framework.test_functional_port_connection_route import (  # pylint: disable=unused-import
    CABLE_CI_ID,
    CABLE_TYPE_ID,
    FRONT_PORT_ID,
    OTHER_CABLE_CI_ID,
    PEER_OBJECT_ID,
    ROUTE_URL,
    SERVER_PORT_ID,
    UNASSIGNED_ROUTE,
    _create,
    _created_id,
    _fill_cable_ci,
    _ipam_licensed,
    fixture_seeded,
)
# -------------------------------------------------------------------------------------------------------------------- #

SECRET_NAME: str = 'SECRET-CABLE'
SECRET_DESCRIPTION: str = 'core uplink, room 4'
CI_VALUE_KEYS: list[str] = [
    CableViewKey.NAME.value, CableViewKey.TYPE.value, CableViewKey.LENGTH.value,
    CableViewKey.COLOR.value, CableViewKey.DESCRIPTION.value,
]
# READ for a group the requesting admin is not in
DENIED_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {'99': ['READ']}}}

# Every read route that renders the connection between SERVER_PORT_ID and FRONT_PORT_ID
READ_URLS: dict[str, str] = {
    'single': '{route}/{connection_id}',
    'of-port': '{route}/port/{port_id}',
    'of-object': '{route}/object/{object_id}',
    'ports-overview': '/ports/object/{object_id}/overview',
    'object-cabling': '/ports/object/{object_id}/cabling',
    'port-cabling': '/ports/{port_id}/cabling',
    'ci-explorer': '/ci_explorer/items?target_id={object_id}&with_root=true',
}


def _cable_blocks(body: Any) -> list[dict[str, Any]]:
    """Every 'cable' block anywhere in a response body, in document order."""
    blocks: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get('cable'), dict):
                blocks.append(node['cable'])
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(body)

    return blocks


@pytest.fixture(name='connection_id')
def fixture_connection_id(rest_api, database_manager: MongoDatabaseManager, database_name: str) -> int:
    """A connection whose cable is the seeded Cable CI, filled with values worth hiding"""
    _fill_cable_ci(database_manager, database_name, **{
        'dg-cable-name': SECRET_NAME, 'dg-cable-description': SECRET_DESCRIPTION,
    })

    return _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID))


@pytest.fixture(name='denied')
def fixture_denied(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The Cable type's READ denied to the requesting admin's group"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.update_one({'public_id': CABLE_TYPE_ID}, {'$set': {'acl': DENIED_ACL}})

    yield


def _url(name: str, connection_id: int) -> str:
    """One of READ_URLS, filled in"""
    return READ_URLS[name].format(
        route=ROUTE_URL, connection_id=connection_id, port_id=SERVER_PORT_ID, object_id=PEER_OBJECT_ID,
    )


@pytest.mark.parametrize('route', list(READ_URLS))
class TestEveryReadWithholdsTheValues:
    """The same answer on every surface that shows a connection's cable"""

    def test_an_unreadable_cable_ci_shows_its_id_and_nothing_else(
            self, rest_api, connection_id: int, denied: None, route: str) -> None:
        """Before: the CI's name and description, though GET /objects/<ci> answered 403"""
        response = rest_api.get(_url(route, connection_id))

        assert response.status_code == HTTPStatus.OK
        blocks = _cable_blocks(response.get_json())
        assert blocks
        assert SECRET_NAME not in response.get_data(as_text=True)
        assert SECRET_DESCRIPTION not in response.get_data(as_text=True)
        for block in blocks:
            assert block[CableViewKey.CABLE_CI_ID.value] == CABLE_CI_ID
            assert block[CableViewKey.RESTRICTED.value] is True
            assert [block[key] for key in CI_VALUE_KEYS] == [None] * len(CI_VALUE_KEYS)

    def test_a_readable_cable_ci_is_shown_as_before(self, rest_api, connection_id: int, route: str) -> None:
        """Nothing changes for a caller who may read the Cable type"""
        response = rest_api.get(_url(route, connection_id))

        blocks = _cable_blocks(response.get_json())
        assert blocks
        assert all(block[CableViewKey.NAME.value] == SECRET_NAME for block in blocks)
        assert all(CableViewKey.RESTRICTED.value not in block for block in blocks)


def test_the_cable_ci_itself_stays_refused(rest_api, connection_id: int, denied: None) -> None:
    """The rule the blocks now follow: the object read answers 403"""
    assert connection_id
    assert rest_api.get(f'/objects/{CABLE_CI_ID}').status_code == HTTPStatus.FORBIDDEN


class TestTheWritesAnswerWithheld:
    """A write naming an unreadable Cable CI is the connection rights' call (Q13) - its answer shows no value"""

    def test_a_create_is_accepted_and_withheld(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str, denied: None) -> None:
        """201, the id kept, restricted, no value"""
        _fill_cable_ci(database_manager, database_name, **{'dg-cable-name': SECRET_NAME})

        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)

        assert response.status_code == HTTPStatus.CREATED
        block: dict[str, Any] = _cable_blocks(response.get_json())[0]
        assert block[CableViewKey.RESTRICTED.value] is True
        assert block[CableViewKey.NAME.value] is None

    def test_an_update_answer_is_withheld(self, rest_api, connection_id: int, denied: None) -> None:
        """The PATCH answer is what a following read returns"""
        response = rest_api.patch(f'{ROUTE_URL}/{connection_id}', json={'cable_ci_id': CABLE_CI_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert SECRET_NAME not in response.get_data(as_text=True)
        assert _cable_blocks(response.get_json())[0][CableViewKey.RESTRICTED.value] is True


class TestThePicker:
    """GET /port_connections/cables/unassigned/ reads its candidates through the caller's READ ACL"""

    def _offered(self, rest_api) -> list[int]:
        response = rest_api.get(f'{ROUTE_URL}{UNASSIGNED_ROUTE}')

        assert response.status_code == HTTPStatus.OK

        return [row['public_id'] for row in response.get_json()['results']]

    def test_an_unreadable_cable_is_not_offered(self, rest_api, denied: None) -> None:
        """Before: listed with every value - a row is nothing but the CI's values"""
        assert OTHER_CABLE_CI_ID not in self._offered(rest_api)
        assert CABLE_CI_ID not in self._offered(rest_api)

    def test_a_readable_cable_is(self, rest_api) -> None:
        """Nothing changes for a caller who may read the Cable type"""
        assert OTHER_CABLE_CI_ID in self._offered(rest_api)

    def test_the_total_counts_what_is_offered(self, rest_api, denied: None) -> None:
        """Narrowed in the criteria, so the count agrees with the rows"""
        response = rest_api.get(f'{ROUTE_URL}{UNASSIGNED_ROUTE}')

        rows: list[dict[str, Any]] = response.get_json()['results']
        assert response.get_json()['total'] == len(rows)
        assert all(row['type_id'] != CABLE_TYPE_ID for row in rows)
