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
Integration tests: a scoped client ``$lookup`` runs on a real MongoDB and joins only readable objects

``lookup_scope.scope_object_lookups`` puts the type exclusion into a join's own pipeline - for the
``localField`` / ``foreignField`` form that means a ``pipeline`` NEXT TO the two fields, which MongoDB accepts
from 5.0 on. These tests run the scoped stages against the collection directly: both join forms and a nested
join return the readable object and never the denied one, and an unscoped join still returns both
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.responses.response_parameters.lookup_scope import scope_object_lookups
# -------------------------------------------------------------------------------------------------------------------- #

READABLE_TYPE_ID: int = 98610
DENIED_TYPE_ID: int = 98611
ANCHOR_ID: int = 98620
READABLE_ID: int = 98621
DENIED_ID: int = 98622
SEEDED_IDS: list[int] = [ANCHOR_ID, READABLE_ID, DENIED_ID]
# The value every seeded object shares, so a localField join on it pulls all three in
SHARED_MARK: str = 'lookup-scope-mark'
JOIN_ALIAS: str = 'joined'


def _object(public_id: int, type_id: int) -> dict[str, Any]:
    """A minimal object document carrying the shared mark."""
    return {'public_id': public_id, 'type_id': type_id, 'mark': SHARED_MARK, 'fields': []}


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """An anchor and two join targets - one of a readable type, one of a denied type"""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': SEEDED_IDS}})
    collection.insert_many([
        _object(ANCHOR_ID, READABLE_TYPE_ID), _object(READABLE_ID, READABLE_TYPE_ID),
        _object(DENIED_ID, DENIED_TYPE_ID),
    ])
    yield collection
    collection.delete_many({'public_id': {'$in': SEEDED_IDS}})


def _joined_ids(collection, join: dict[str, Any], denied: list[int]) -> set[int]:
    """Runs the anchor through the (scoped) join and answers the public_ids of the joined documents."""
    pipeline = [{'$match': {'public_id': ANCHOR_ID}}, *scope_object_lookups([join], denied)]
    (anchor,) = list(collection.aggregate(pipeline))

    return {joined['public_id'] for joined in anchor[JOIN_ALIAS]} - {ANCHOR_ID}


PIPELINE_JOIN: dict[str, Any] = {'$lookup': {
    'from': CmdbObject.COLLECTION, 'pipeline': [{'$match': {'public_id': {'$in': [READABLE_ID, DENIED_ID]}}}],
    'as': JOIN_ALIAS,
}}
FIELD_JOIN: dict[str, Any] = {'$lookup': {
    'from': CmdbObject.COLLECTION, 'localField': 'mark', 'foreignField': 'mark', 'as': JOIN_ALIAS,
}}


@pytest.mark.parametrize('join', [pytest.param(PIPELINE_JOIN, id='pipeline form'),
                                  pytest.param(FIELD_JOIN, id='localField form')])
def test_a_scoped_join_returns_only_the_readable_object(objects, join: dict[str, Any]) -> None:
    """The denied type's object is not joined - the localField + pipeline combination runs on this server"""
    assert _joined_ids(objects, join, [DENIED_TYPE_ID]) == {READABLE_ID}


@pytest.mark.parametrize('join', [pytest.param(PIPELINE_JOIN, id='pipeline form'),
                                  pytest.param(FIELD_JOIN, id='localField form')])
def test_an_unscoped_join_returns_both(objects, join: dict[str, Any]) -> None:
    """Nothing denied: the join is left as sent and finds both - the control for the test above"""
    assert _joined_ids(objects, join, []) == {READABLE_ID, DENIED_ID}


def test_a_nested_join_is_scoped_on_the_server(objects) -> None:
    """A join inside a join's pipeline drops the denied object too"""
    nested: dict[str, Any] = {'$lookup': {
        'from': CmdbObject.COLLECTION,
        'pipeline': [{'$match': {'public_id': ANCHOR_ID}}, {'$lookup': {**FIELD_JOIN['$lookup'], 'as': 'inner'}}],
        'as': JOIN_ALIAS,
    }}
    pipeline = [{'$match': {'public_id': ANCHOR_ID}}, *scope_object_lookups([nested], [DENIED_TYPE_ID])]
    (anchor,) = list(objects.aggregate(pipeline))

    inner_ids = {doc['public_id'] for joined in anchor[JOIN_ALIAS] for doc in joined['inner']}
    assert DENIED_ID not in inner_ids
    assert READABLE_ID in inner_ids
