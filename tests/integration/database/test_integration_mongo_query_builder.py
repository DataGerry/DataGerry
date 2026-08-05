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
Integration tests for cmdb.database.mongo_query_builder against a real MongoDB

Pins the *matching semantics* of the queries MongoDBQueryBuilder produces - in particular the nested
``multi_data_sections.values.data`` $elemMatch path for multi-data-section fields, the flat ``fields``
path, the regex-escaped ``contains`` operator and the element-wise coerced ``in`` operator over a
number field. The built query document is run directly against the object collection with find(), so
the assertions reflect what MongoDB actually matches, not just the query shape.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager, MongoDBQueryBuilder
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9401
OTHER_TYPE_ID: int = 9402

OBJ_MATCH: int = 9411       # txt1='alpha', num1=10, mds1='match'
OBJ_OTHER: int = 9412       # txt1='beta',  num1=20, mds1='other'
OBJ_OTHER_TYPE: int = 9421  # same field values as OBJ_MATCH but a different type_id
ALL_SEEDED_IDS: list[int] = [OBJ_MATCH, OBJ_OTHER, OBJ_OTHER_TYPE]

MDS_SECTION_ID: str = 'mds-sec'


def _report_type() -> CmdbType:
    """A CmdbType with a number, a text and a multi-data-section text field."""
    return CmdbType.from_data({
        'public_id': TYPE_ID,
        'name': 'qb_demo',
        'label': 'QB Demo',
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [
            {'type': 'number', 'name': 'num1', 'label': 'Num'},
            {'type': 'text', 'name': 'txt1', 'label': 'Txt'},
            {'type': 'text', 'name': 'mds1', 'label': 'MDS field'},
        ],
        'render_meta': {
            'icon': 'fas fa-cube',
            'externals': [],
            'summary': {'fields': []},
            'sections': [
                {'type': 'multi-data-section', 'name': MDS_SECTION_ID, 'label': 'MDS', 'fields': ['mds1']},
                {'type': 'section', 'name': 'info', 'label': 'Info', 'fields': ['num1', 'txt1']},
            ],
        },
    })


def _object_doc(public_id: int, type_id: int, txt: str, num: int, mds: str) -> dict[str, Any]:
    """Builds a CmdbObject doc with flat fields and a single multi-data-section row."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [
            {'name': 'num1', 'value': num, 'type': 'number'},
            {'name': 'txt1', 'value': txt, 'type': 'text'},
            {'name': 'mds1', 'value': mds, 'type': 'text'},
        ],
        'multi_data_sections': [
            {'section_id': MDS_SECTION_ID, 'values': [{'data': [{'name': 'mds1', 'value': mds, 'type': 'text'}]}]},
        ],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_objects_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds three CmdbObject docs (two of TYPE_ID, one of OTHER_TYPE_ID) and removes them after."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    collection.insert_many([
        _object_doc(OBJ_MATCH, TYPE_ID, 'alpha', 10, 'match'),
        _object_doc(OBJ_OTHER, TYPE_ID, 'beta', 20, 'other'),
        _object_doc(OBJ_OTHER_TYPE, OTHER_TYPE_ID, 'alpha', 10, 'match'),
    ])
    yield
    collection.delete_many({'public_id': {'$in': ALL_SEEDED_IDS}})


@pytest.fixture(name='collection')
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str):
    """The object collection bound to the test database."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name)


def _matched_ids(collection, conditions: dict[str, Any]) -> set[int]:
    """Builds the query for the given conditions and returns the public_ids it matches."""
    query = MongoDBQueryBuilder(conditions, _report_type()).build()
    return {doc['public_id'] for doc in collection.find(query)}


class TestQueryMatching:
    """The query documents produced by MongoDBQueryBuilder match the intended objects in MongoDB."""

    def test_type_only_query_matches_all_of_the_type(self, collection) -> None:
        """A condition-less report matches every object of the type and excludes other types."""
        assert _matched_ids(collection, None) == {OBJ_MATCH, OBJ_OTHER}

    def test_flat_field_equality_matches(self, collection) -> None:
        """An '=' rule on a flat field matches the object carrying that value (same type only)."""
        conditions = {'condition': 'and', 'rules': [{'field': 'txt1', 'operator': '=', 'value': 'alpha'}]}
        assert _matched_ids(collection, conditions) == {OBJ_MATCH}

    def test_contains_is_literal_after_escaping(self, collection) -> None:
        """'contains' matches a substring; the escaped value is matched literally, not as a pattern."""
        conditions = {'condition': 'and', 'rules': [{'field': 'txt1', 'operator': 'contains', 'value': 'lph'}]}
        assert _matched_ids(collection, conditions) == {OBJ_MATCH}

    def test_mds_field_equality_matches_via_nested_elem_match(self, collection) -> None:
        """An '=' rule on a multi-data-section field matches via the nested values.data $elemMatch path."""
        conditions = {'condition': 'and', 'rules': [{'field': 'mds1', 'operator': '=', 'value': 'match'}]}
        assert _matched_ids(collection, conditions) == {OBJ_MATCH}

    def test_number_in_list_matches_after_element_coercion(self, collection) -> None:
        """A number field with 'in' over string values matches once each element is coerced to int."""
        conditions = {'condition': 'or', 'rules': [{'field': 'num1', 'operator': 'in', 'value': ['10', '99']}]}
        assert _matched_ids(collection, conditions) == {OBJ_MATCH}
