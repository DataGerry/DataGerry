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
What the object routes answer for a reference-section chain in the shape the type builder writes

A's reference section pulls B's reference section, which pulls C's main section. The object view and the
rendered list both carry, on B's pulled-in field, the block the frontend's ref-section component draws -
C's values under C's type - rather than a bare id it shows as "No reference set"
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from tests.utils import reference_chain_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'
CHAIN_FILTER: str = json.dumps({'public_id': {'$in': [seed.A_ID, seed.SECOND_A_ID]}})
BLOCK_KEYS: set[str] = {'type_id', 'type_name', 'type_label', 'type_icon', 'fields'}


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the chain for each test and removes it after."""
    seed.seed(database_manager, database_name)
    yield
    seed.purge(database_manager, database_name)


class TestTheObjectView:
    """GET /objects/<id>."""

    def test_the_nested_block_carries_the_far_value(self, rest_api) -> None:
        """B's pulled-in field carries C's value"""
        response = rest_api.get(f'{ROUTE_URL}/{seed.A_ID}')

        assert response.status_code == HTTPStatus.OK
        assert [field['value'] for field in seed.nested_block(response.get_json())['fields']] == [seed.C_VALUE]

    def test_the_nested_block_has_the_frontend_shape(self, rest_api) -> None:
        """The five keys ref-section.component and ref-section-simple.component read"""
        block: dict[str, Any] = seed.nested_block(rest_api.get(f'{ROUTE_URL}/{seed.A_ID}').get_json())

        assert set(block) == BLOCK_KEYS
        assert block['type_id'] == seed.C_TYPE_ID


class TestTheRenderedList:
    """GET /objects/?view=render."""

    def test_every_row_carries_the_chain(self, rest_api) -> None:
        """Both A objects, one chain"""
        response = rest_api.get(f'{ROUTE_URL}/?view=render&limit=0&filter={CHAIN_FILTER}')

        assert response.status_code == HTTPStatus.OK
        rows: list[dict[str, Any]] = response.get_json()['results']
        assert len(rows) == 2
        assert all([field['value'] for field in seed.nested_block(row)['fields']] == [seed.C_VALUE] for row in rows)
