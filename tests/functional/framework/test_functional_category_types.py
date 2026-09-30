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
Functional coverage of what a CmdbCategory's ``types`` may hold

The two write routes accept only ids of existing CmdbTypes, each once, and a type that no other category
holds - what the frontend's category form already assumes. And the two reads a stored document entry
would break (the category tree, the uncategorized-types listing) skip it instead of answering 500
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_constants import (
    CATEGORY_TYPES_CLAIMED_MSG,
    CATEGORY_TYPES_NOT_IDS_MSG,
    CATEGORY_TYPES_REPEATED_MSG,
    CATEGORY_TYPES_UNKNOWN_MSG,
)
from cmdb.models.category_model import CmdbCategory
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/categories'

TYPE_A: int = 9691
TYPE_B: int = 9692
MISSING_TYPE: int = 9699
HOLDER_ID: int = 9701
EDITED_ID: int = 9702
JUNK_ID: int = 9703
ALL_CATEGORY_IDS: list[int] = [HOLDER_ID, EDITED_ID, JUNK_ID]
NEW_NAME: str = 'category-types-new'


def _payload(name: str, types: list[Any]) -> dict[str, Any]:
    """A category write body."""
    return {'name': name, 'label': name, 'parent': None, 'types': types}


@pytest.fixture(name='categories')
def fixture_categories(database_manager: MongoDatabaseManager, database_name: str):
    """Two types, a category holding TYPE_A and an empty one to edit; everything removed afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [TYPE_A, TYPE_B]}})
        categories.delete_many({'$or': [{'public_id': {'$in': ALL_CATEGORY_IDS}}, {'name': NEW_NAME}]})

    _purge()
    types.insert_many([make_type_doc(TYPE_A, 'category-types-a'), make_type_doc(TYPE_B, 'category-types-b')])
    categories.insert_many([
        {'public_id': HOLDER_ID, **_payload('category-types-holder', [TYPE_A])},
        {'public_id': EDITED_ID, **_payload('category-types-edited', [])},
    ])
    yield categories
    _purge()


class TestWhatAWriteMayName:
    """POST and PUT /categories/."""

    @pytest.mark.parametrize('entry', [{'a': 1}, 'x', 0, -1], ids=['document', 'string', 'zero', 'negative'])
    def test_an_entry_that_is_no_id_is_refused(self, rest_api, categories, entry: Any) -> None:
        """The schema's item rule"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(NEW_NAME, [entry]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert categories.find_one({'name': NEW_NAME}) is None

    def test_a_boolean_is_refused_by_name(self, rest_api, categories) -> None:
        """It passes the schema's integer rule, so the route names it"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(NEW_NAME, [True]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CATEGORY_TYPES_NOT_IDS_MSG.format(values=[True])

    def test_a_repeated_type_is_refused(self, rest_api, categories) -> None:
        """Named once"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(NEW_NAME, [TYPE_B, TYPE_B]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CATEGORY_TYPES_REPEATED_MSG.format(type_ids=[TYPE_B])

    def test_an_unknown_type_is_refused(self, rest_api, categories) -> None:
        """An id no CmdbType carries"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(NEW_NAME, [TYPE_B, MISSING_TYPE]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CATEGORY_TYPES_UNKNOWN_MSG.format(type_ids=[MISSING_TYPE])

    def test_a_type_another_category_holds_is_refused(self, rest_api, categories) -> None:
        """A type sits in at most one category - on the update as on the create"""
        response = rest_api.put(f'{ROUTE_URL}/{EDITED_ID}', json=_payload('category-types-edited', [TYPE_A]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CATEGORY_TYPES_CLAIMED_MSG.format(
            claims=f'Type {TYPE_A} in Category [{HOLDER_ID}]')
        assert categories.find_one({'public_id': EDITED_ID})['types'] == []

    def test_a_category_keeping_its_own_types_saves(self, rest_api, categories) -> None:
        """Its own current types are no clash"""
        response = rest_api.put(f'{ROUTE_URL}/{HOLDER_ID}', json=_payload('category-types-holder', [TYPE_A, TYPE_B]))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert categories.find_one({'public_id': HOLDER_ID})['types'] == [TYPE_A, TYPE_B]

    def test_an_unassigned_existing_type_is_accepted(self, rest_api, categories) -> None:
        """The control"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(NEW_NAME, [TYPE_B]))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)


class TestStoredJunkDoesNotBreakTheReads:
    """A document entry stored before the rule."""

    @pytest.fixture(autouse=True)
    def _junk(self, categories):
        """A category holding a document entry next to a real type id."""
        categories.insert_one({'public_id': JUNK_ID, **_payload('category-types-junk', [{'a': 1}, TYPE_B])})

    def test_the_tree_still_answers(self, rest_api) -> None:
        """A stored document entry does not make it a 500 for every user"""
        assert rest_api.get(f'{ROUTE_URL}/?view=tree').status_code == HTTPStatus.OK

    def test_the_uncategorized_listing_still_answers(self, rest_api) -> None:
        """Nor this one; the readable entry beside the junk still counts as assigned"""
        response = rest_api.get('/types/?uncategorized=true&limit=0')

        assert response.status_code == HTTPStatus.OK
        assert TYPE_B not in {a_type['public_id'] for a_type in response.get_json()['results']}
