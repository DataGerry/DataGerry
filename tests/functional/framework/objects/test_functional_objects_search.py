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
Functional tests for ``?search=`` on the object listing and the reference listing

The free-text search the Angular app would otherwise assemble as a nine-stage aggregation and post
through ``?filter=``. What matters here is what it matches - a term
has to find an object by its own field value **and** by the field values of the objects it references,
which is the whole reason the query needed a join - and what it does not do: it is a literal, it drops
no fields from the documents it returns, and the total counts what it returned.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from tests.functional.framework.objects.objects_route_helpers import (
    NAME_FIELD,
    ROUTE_URL,
    SEED_AUTHOR_ID,
    SEED_VERSION,
    TYPE_ID,
    object_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

REF_TYPE_ID: int = 9470
REF_FIELD: str = 'ref-field'

TARGET_ID: int = 9471
SOURCE_ID: int = 9472
UNRELATED_ID: int = 9473

TARGET_VALUE: str = 'Findable Target'
SOURCE_VALUE: str = 'Source Row'
UNRELATED_VALUE: str = 'Nothing Special'
PUNCTUATION_VALUE: str = 'C++ (EU)'

SEARCH_IDS: list[int] = [TARGET_ID, SOURCE_ID, UNRELATED_ID]


def _ref_type_doc() -> dict[str, Any]:
    """A CmdbType whose objects carry a reference to another object."""
    return {
        'public_id': REF_TYPE_ID,
        'name': 'search-ref-type',
        'label': 'Search Ref Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
            {'type': 'ref', 'name': REF_FIELD, 'label': 'Ref', 'ref_types': [TYPE_ID]},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                          'fields': [NAME_FIELD, REF_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': {}}},
        'version': SEED_VERSION,
    }


def _referencing_object_doc(public_id: int, value: str, target_id: int) -> dict[str, Any]:
    """An object of the reference type, pointing at the target object."""
    doc = object_doc(public_id, value)
    doc['type_id'] = REF_TYPE_ID
    doc['fields'] = [
        {'type': 'text', 'name': NAME_FIELD, 'value': value},
        {'type': 'ref', 'name': REF_FIELD, 'value': target_id},
    ]

    return doc


def _listed_ids(response) -> list[int]:
    """The public_ids in a listing response."""
    return [result['public_id'] for result in response.get_json()['results']]


@pytest.fixture(name='seed_search_objects', autouse=True)
def fixture_seed_search_objects(database_manager: MongoDatabaseManager, database_name: str):
    """A target object, an object referencing it, and one related to neither."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_one(_ref_type_doc())
    objects.insert_one(object_doc(TARGET_ID, TARGET_VALUE))
    objects.insert_one(_referencing_object_doc(SOURCE_ID, SOURCE_VALUE, TARGET_ID))
    objects.insert_one(object_doc(UNRELATED_ID, UNRELATED_VALUE))

    yield

    types.delete_one({'public_id': REF_TYPE_ID})
    objects.delete_many({'public_id': {'$in': SEARCH_IDS}})


class TestObjectListSearch:
    """``GET /objects/?search=`` matches own values, referenced values and the identity fields."""

    def test_a_term_matches_an_objects_own_field_value(self, rest_api) -> None:
        """The ordinary case."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&search={TARGET_VALUE}')

        assert response.status_code == HTTPStatus.OK
        assert TARGET_ID in _listed_ids(response)

    def test_a_term_matches_through_a_reference(self, rest_api) -> None:
        """
        The reason this query needs a join at all

        The source object carries the target's public_id, not its text - so a search for the target's
        name has to find the source too, or a user searching for a customer never finds the servers
        pointing at that customer.
        """
        listed = _listed_ids(rest_api.get(f'{ROUTE_URL}/?limit=0&search={TARGET_VALUE}'))

        assert SOURCE_ID in listed

    def test_an_unrelated_object_is_not_matched(self, rest_api) -> None:
        """The precondition: the search narrows rather than returning everything."""
        listed = _listed_ids(rest_api.get(f'{ROUTE_URL}/?limit=0&search={TARGET_VALUE}'))

        assert UNRELATED_ID not in listed

    def test_a_term_matches_the_public_id(self, rest_api) -> None:
        """A user pasting an id into the search box expects to land on that object."""
        listed = _listed_ids(rest_api.get(f'{ROUTE_URL}/?limit=0&search={TARGET_ID}'))

        assert TARGET_ID in listed

    def test_the_total_counts_what_was_returned(self, rest_api) -> None:
        """The search is part of the criteria, so the count aggregation applies it too."""
        body = rest_api.get(f'{ROUTE_URL}/?limit=0&search={TARGET_VALUE}').get_json()

        assert body['total'] == len(body['results'])

    def test_an_empty_search_changes_nothing(self, rest_api) -> None:
        """An absent or blank term adds no stages, so the listing is the unsearched one."""
        without = rest_api.get(f'{ROUTE_URL}/?limit=0').get_json()['total']
        blank = rest_api.get(f'{ROUTE_URL}/?limit=0&search=').get_json()['total']

        assert without == blank

    def test_a_search_that_matches_nothing_is_an_empty_list(self, rest_api) -> None:
        """Not an error, and not the whole collection."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&search=no-such-text-anywhere-xyz')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'] == []

    def test_the_search_combines_with_a_client_filter(self, rest_api) -> None:
        """``?search=`` narrows the caller's own filter rather than replacing it."""
        listed = _listed_ids(rest_api.get(
            f'{ROUTE_URL}/?limit=0&search={TARGET_VALUE}&filter={{"public_id":{UNRELATED_ID}}}'
        ))

        assert listed == []

    def test_the_returned_documents_keep_every_field(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        The browser's pipeline rebuilt each document with an explicit ``$project``

        Anything it did not list was dropped, so a searched listing answered thinner objects than an
        unsearched one. These stages only add working fields and remove them again.
        """
        body = rest_api.get(f'{ROUTE_URL}/?limit=0&search={TARGET_VALUE}&view=native').get_json()
        searched = next(row for row in body['results'] if row['public_id'] == TARGET_ID)

        stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
            {'public_id': TARGET_ID}
        )

        assert set(stored) - {'_id'} <= set(searched)


class TestObjectListSearchIsLiteral:
    """The term is text the user typed, not a pattern."""

    @pytest.fixture(autouse=True)
    def _seed_punctuation(self, database_manager: MongoDatabaseManager, database_name: str):
        """One object whose value is full of regex metacharacters."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        objects.insert_one(object_doc(UNRELATED_ID + 1, PUNCTUATION_VALUE))
        yield
        objects.delete_one({'public_id': UNRELATED_ID + 1})

    def test_punctuation_is_matched_as_itself(self, rest_api) -> None:
        """`C++ (EU)` finds `C++ (EU)` - it is not a quantifier and a capture group."""
        listed = _listed_ids(rest_api.get(f'{ROUTE_URL}/?limit=0&search=C%2B%2B%20(EU)'))

        assert UNRELATED_ID + 1 in listed

    def test_a_wildcard_matches_nothing_rather_than_everything(self, rest_api) -> None:
        """`.*` is two characters to search for, not a pattern that matches every object."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&search=.%2A')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'] == []

    def test_an_unbalanced_bracket_is_answered_not_refused(self, rest_api) -> None:
        """An invalid pattern would be a 400 from the database; a literal is just a search."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&search=%5Bunclosed')

        assert response.status_code == HTTPStatus.OK

    def test_the_search_is_case_insensitive(self, rest_api) -> None:
        """A search box matches regardless of case."""
        listed = _listed_ids(rest_api.get(f'{ROUTE_URL}/?limit=0&search={TARGET_VALUE.lower()}'))

        assert TARGET_ID in listed


class TestObjectReferencesSearch:
    """``GET /objects/references/<id>?search=`` takes the same term with the same meaning."""

    def test_the_reference_listing_accepts_the_search(self, rest_api) -> None:
        """The objects referencing the target, narrowed to those matching the term."""
        response = rest_api.get(f'{ROUTE_URL}/references/{TARGET_ID}?limit=0&search={SOURCE_VALUE}')

        assert response.status_code == HTTPStatus.OK
        assert SOURCE_ID in _listed_ids(response)

    def test_a_non_matching_term_empties_the_reference_listing(self, rest_api) -> None:
        """It narrows rather than being ignored."""
        response = rest_api.get(f'{ROUTE_URL}/references/{TARGET_ID}?limit=0&search=no-such-text-xyz')

        assert response.status_code == HTTPStatus.OK
        assert SOURCE_ID not in _listed_ids(response)
