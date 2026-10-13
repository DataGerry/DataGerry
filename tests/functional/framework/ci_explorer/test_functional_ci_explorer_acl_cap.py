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
GET /ci_explorer/items under an item_limit, for a caller who may not read some neighbours - end to end

The neighbours of a type with a locked ACL (which denies every group, the suite's admin included) have the LOWEST
ids, so they would be read first under the sorted cap. They must neither take a slot nor change the answer: every
cap returns the readable neighbour, the same as no cap - for the relation source and the location source alike. A
hidden focal object is a 404 under a cap too
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from tests.utils.ci_explorer_acl_cap_seed import (
    FOCAL_ID,
    HIDDEN_FOCAL_ID,
    LOCATION_FOCAL_ID,
    LOCATION_READABLE_CHILD_ID,
    READABLE_ID,
    purge,
    seed,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ci_explorer/items'


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The cap-and-ACL seed, removed by id after"""
    seed(database_manager, database_name)
    yield
    purge(database_manager, database_name)


def _ids(body: dict[str, Any], bucket: str) -> list[int]:
    """The public_ids in one bucket of a response body"""
    return sorted(node['linked_object']['public_id'] for node in body.get(bucket, []))


class TestTheRelationSource:
    """Two hidden neighbours sort ahead of the readable one."""

    @pytest.mark.parametrize('item_limit', [0, 1, 2, 3, 10])
    def test_every_cap_answers_the_readable_neighbour(self, rest_api, item_limit: int) -> None:
        """Cap 1 and 2 used to answer an empty graph - the hidden neighbours had taken the slots"""
        body = rest_api.get(f'{ROUTE_URL}?target_id={FOCAL_ID}&target_type=CHILD&item_limit={item_limit}').get_json()

        assert _ids(body, 'children_nodes') == [READABLE_ID]

    def test_the_answer_does_not_reveal_how_many_neighbours_are_hidden(self, rest_api) -> None:
        """Trying caps learns nothing: every cap gives the same graph"""
        bodies = [rest_api.get(f'{ROUTE_URL}?target_id={FOCAL_ID}&target_type=CHILD&item_limit={cap}').get_json()
                  for cap in (1, 2, 3)]

        assert bodies[0] == bodies[1] == bodies[2]


class TestTheLocationSource:
    """Two hidden location children sort ahead of the readable one."""

    @pytest.mark.parametrize('item_limit', [0, 1, 2])
    def test_every_cap_answers_the_readable_child(self, rest_api, item_limit: int) -> None:
        """The location children land in the parent bucket (the directions are inverted on purpose)"""
        body = rest_api.get(f'{ROUTE_URL}?target_id={LOCATION_FOCAL_ID}&target_type=PARENT&with_locations=true'
                            f'&item_limit={item_limit}').get_json()

        assert _ids(body, 'parent_nodes') == [LOCATION_READABLE_CHILD_ID]


class TestAHiddenTarget:
    """A 404 under a cap too - the same answer a missing object gets."""

    def test_it_is_404_like_a_missing_one(self, rest_api) -> None:
        """No graph, no hint"""
        hidden = rest_api.get(f'{ROUTE_URL}?target_id={HIDDEN_FOCAL_ID}&item_limit=2')
        missing = rest_api.get(f'{ROUTE_URL}?target_id=98599&item_limit=2')

        assert hidden.status_code == missing.status_code == HTTPStatus.NOT_FOUND
