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


# -------------------------------------------------------------------------------------------------------------------- #
#                                   date day-granularity + is-null missing entries                                     #
# -------------------------------------------------------------------------------------------------------------------- #

DATE_TYPE_ID: int = 9403

OBJ_SAME_DAY_AFTERNOON: int = 9431  # d1 = 2026-08-06 14:30, t1 = 'x'
OBJ_SAME_DAY_MIDNIGHT: int = 9432   # d1 = 2026-08-06 00:00, t1 = ''
OBJ_NEXT_DAY: int = 9433            # d1 = 2026-08-07 09:00, t1 = None
OBJ_NO_TEXT_ENTRY: int = 9434       # d1 = 2026-08-06 08:00, no t1 entry at all

DATE_OBJECT_IDS: list[int] = [
    OBJ_SAME_DAY_AFTERNOON, OBJ_SAME_DAY_MIDNIGHT, OBJ_NEXT_DAY, OBJ_NO_TEXT_ENTRY,
]

TARGET_DAY: str = '2026-08-06'


def _date_type() -> CmdbType:
    """A CmdbType with a date field and a text field."""
    return CmdbType.from_data({
        'public_id': DATE_TYPE_ID,
        'name': 'qb_date_demo',
        'label': 'QB Date Demo',
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [
            {'type': 'date', 'name': 'd1', 'label': 'Date'},
            {'type': 'text', 'name': 't1', 'label': 'Txt'},
        ],
        'render_meta': {
            'icon': 'fas fa-cube',
            'externals': [],
            'summary': {'fields': []},
            'sections': [{'type': 'section', 'name': 'info', 'label': 'Info', 'fields': ['d1', 't1']}],
        },
    })


def _date_object_doc(public_id: int, stamp: datetime, text_entry: dict[str, Any] | None) -> dict[str, Any]:
    """Builds an object of the date type; text_entry is omitted entirely when None."""
    fields: list[dict[str, Any]] = [{'name': 'd1', 'value': stamp, 'type': 'date'}]

    if text_entry is not None:
        fields.append(text_entry)

    return {
        'public_id': public_id,
        'type_id': DATE_TYPE_ID,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': fields,
    }


@pytest.fixture(name='_seed_date_objects', scope='module', autouse=True)
def fixture_seed_date_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds four objects covering both sides of a day boundary and a missing text entry."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': DATE_OBJECT_IDS}})
    collection.insert_many([
        _date_object_doc(OBJ_SAME_DAY_AFTERNOON, datetime(2026, 8, 6, 14, 30, tzinfo=timezone.utc),
                         {'name': 't1', 'value': 'x', 'type': 'text'}),
        _date_object_doc(OBJ_SAME_DAY_MIDNIGHT, datetime(2026, 8, 6, 0, 0, tzinfo=timezone.utc),
                         {'name': 't1', 'value': '', 'type': 'text'}),
        _date_object_doc(OBJ_NEXT_DAY, datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc),
                         {'name': 't1', 'value': None, 'type': 'text'}),
        _date_object_doc(OBJ_NO_TEXT_ENTRY, datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc), None),
    ])
    yield
    collection.delete_many({'public_id': {'$in': DATE_OBJECT_IDS}})


def _date_matched_ids(collection, field: str, operator: str, value: Any) -> set[int]:
    """Runs a single-rule report query of the date type and returns the matched public_ids."""
    conditions = {'condition': 'and', 'rules': [{'field': field, 'operator': operator, 'value': value}]}
    query = MongoDBQueryBuilder(conditions, _date_type()).build()

    return {doc['public_id'] for doc in collection.find(query)}


class TestDateDayGranularity:
    """A date rule carries only a day, so every comparison spans that whole day."""

    def test_equals_matches_the_whole_day(self, collection) -> None:
        """Regression: '=' used to match only an object stamped exactly at midnight."""
        assert _date_matched_ids(collection, 'd1', '=', TARGET_DAY) == {
            OBJ_SAME_DAY_AFTERNOON, OBJ_SAME_DAY_MIDNIGHT, OBJ_NO_TEXT_ENTRY,
        }

    def test_less_than_or_equal_includes_the_whole_day(self, collection) -> None:
        """Regression: '<=' used to drop everything after 00:00:00 on the given date."""
        assert _date_matched_ids(collection, 'd1', '<=', TARGET_DAY) == {
            OBJ_SAME_DAY_AFTERNOON, OBJ_SAME_DAY_MIDNIGHT, OBJ_NO_TEXT_ENTRY,
        }

    def test_greater_than_excludes_the_whole_day(self, collection) -> None:
        """Regression: '>' used to still return the rest of the given date."""
        assert _date_matched_ids(collection, 'd1', '>', TARGET_DAY) == {OBJ_NEXT_DAY}

    def test_greater_than_or_equal_starts_at_midnight(self, collection) -> None:
        """'>=' was already correct and still returns the day itself plus everything after."""
        assert _date_matched_ids(collection, 'd1', '>=', TARGET_DAY) == set(DATE_OBJECT_IDS)

    def test_less_than_excludes_the_day_itself(self, collection) -> None:
        """'<' was already correct: nothing was stamped before the target day."""
        assert _date_matched_ids(collection, 'd1', '<', TARGET_DAY) == set()

    def test_not_equals_excludes_the_whole_day(self, collection) -> None:
        """'!=' negates the day range, so same-day objects are all excluded."""
        assert _date_matched_ids(collection, 'd1', '!=', TARGET_DAY) == {OBJ_NEXT_DAY}


class TestIsNullMatchesMissingEntries:
    """'is null' reaches objects that carry no entry for the field at all."""

    def test_is_null_includes_empty_none_and_missing(self, collection) -> None:
        """Regression: an object with no entry for the field could never be matched by $elemMatch."""
        assert _date_matched_ids(collection, 't1', 'is null', None) == {
            OBJ_SAME_DAY_MIDNIGHT, OBJ_NEXT_DAY, OBJ_NO_TEXT_ENTRY,
        }

    def test_is_not_null_only_matches_a_real_value(self, collection) -> None:
        """The counterpart is unchanged: no entry means no value, so it stays excluded."""
        assert _date_matched_ids(collection, 't1', 'is not null', None) == {OBJ_SAME_DAY_AFTERNOON}
