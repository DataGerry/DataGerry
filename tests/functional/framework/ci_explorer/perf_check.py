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
Post-refactor perf sanity check for /ci_explorer/items

Seeds a moderately sized fixture (N linked objects, each with a ref-typed field) and
times five invocations of the route. Reports the median wall-clock so the post-refactor
numbers can be eyeballed against expectations - this is a sanity test, not a benchmark
suite. The big perf win (batched ref-field flattening) is structural: each ref field
previously triggered its own get_summary_line round trip; now one bulk lookup serves
the whole batch
"""
from datetime import datetime, timezone
from http import HTTPStatus
from statistics import median
import time
from typing import Any

import pytest
from pymongo.mongo_client import MongoClient

from cmdb.database.mongo_connector import MongoConnector
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ci_explorer/items'
N_LINKED: int = 30

TYPE_TARGET: int = 20
TYPE_NEIGHBOUR: int = 21
TYPE_REF_TARGET: int = 22  # the type pointed at by the ref fields, used to test batched summary lookup

OBJ_TARGET: int = 5000
OBJ_REF_BASE: int = 6000  # ref targets occupy OBJ_REF_BASE .. OBJ_REF_BASE + N_LINKED
OBJ_LINKED_BASE: int = 7000  # linked objects occupy OBJ_LINKED_BASE .. OBJ_LINKED_BASE + N_LINKED

RELATION_ID: int = 9000


def _now() -> datetime:
    """Returns a UTC-aware datetime suitable for the *_time fields on every model."""
    return datetime.now(timezone.utc)


def _type_doc(public_id: int, label: str, with_ref_field: bool = False) -> dict[str, Any]:
    """Builds a CmdbType doc; optionally declares a ref-typed 'owner' field for the batching test."""
    fields = [{'type': 'text', 'name': 'name', 'label': 'Name'}]
    if with_ref_field:
        fields.append({'type': 'ref', 'name': 'owner', 'label': 'Owner', 'ref_types': [TYPE_REF_TARGET]})

    return {
        'public_id': public_id,
        'name': label.lower(),
        'label': label,
        'author_id': 1,
        'creation_time': _now(),
        'active': True,
        'fields': fields,
        'render_meta': {'icon': 'fa-cube', 'sections': [], 'summary': {'fields': ['name']}},
        'ci_explorer_label': 'name',
        'ci_explorer_color': '#1f77b4',
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


def _object_doc(public_id: int, type_id: int, name: str, owner_ref: int | None = None) -> dict[str, Any]:
    """Builds a CmdbObject doc; optionally carries a ref-typed 'owner' field for batching."""
    fields: list[dict[str, Any]] = [{'name': 'name', 'value': name}]
    if owner_ref is not None:
        fields.append({'name': 'owner', 'value': owner_ref})

    return {
        'public_id': public_id,
        'type_id': type_id,
        'status': True,
        'active': True,
        'author_id': 1,
        'creation_time': _now(),
        'version': '1.0.0',
        'fields': fields,
    }


@pytest.fixture(scope='module', name='connector')
def fixture_connector(database_manager) -> MongoConnector:
    """Shortcut to the underlying MongoConnector for direct collection access."""
    return database_manager.connector


@pytest.fixture(scope='module', autouse=True)
def setup_perf_fixture(request, connector: MongoConnector, database_name):
    """Seeds 30 linked objects + their ref targets + the target object + N object_relations."""
    db = connector.client.get_database(database_name)
    types = db.get_collection(CmdbType.COLLECTION)
    objects = db.get_collection(CmdbObject.COLLECTION)
    relations = db.get_collection(CmdbRelation.COLLECTION)
    object_relations = db.get_collection(CmdbObjectRelation.COLLECTION)

    types.insert_many([
        _type_doc(TYPE_TARGET, 'PerfTarget'),
        _type_doc(TYPE_NEIGHBOUR, 'PerfNeighbour', with_ref_field=True),
        _type_doc(TYPE_REF_TARGET, 'PerfRefTarget'),
    ])

    object_batch: list[dict[str, Any]] = [_object_doc(OBJ_TARGET, TYPE_TARGET, 'perf-target')]

    for idx in range(N_LINKED):
        ref_id = OBJ_REF_BASE + idx
        linked_id = OBJ_LINKED_BASE + idx
        object_batch.append(_object_doc(ref_id, TYPE_REF_TARGET, f'perf-ref-{idx}'))
        object_batch.append(_object_doc(linked_id, TYPE_NEIGHBOUR, f'perf-neighbour-{idx}', owner_ref=ref_id))

    objects.insert_many(object_batch)

    relations.insert_one({
        'public_id': RELATION_ID,
        'relation_name': 'perf-connected',
        'parent_type_ids': [TYPE_TARGET],
        'child_type_ids': [TYPE_NEIGHBOUR],
        'relation_name_parent': 'hosts',
        'relation_name_child': 'hosted_by',
        'relation_color_parent': '#33aa33',
        'relation_color_child': '#aa3333',
        'relation_icon_parent': 'fa-arrow-right',
        'relation_icon_child': 'fa-arrow-left',
        'description': 'perf fixture relation',
        'sections': [],
        'fields': [],
    })

    object_relations.insert_many([
        {
            'public_id': 10_000 + idx,
            'relation_id': RELATION_ID,
            'relation_parent_id': OBJ_TARGET,
            'relation_parent_type_id': TYPE_TARGET,
            'relation_child_id': OBJ_LINKED_BASE + idx,
            'relation_child_type_id': TYPE_NEIGHBOUR,
            'author_id': 1,
            'creation_time': _now(),
            'last_edit_time': None,
            'field_values': [],
        }
        for idx in range(N_LINKED)
    ])

    def _drop_all():
        types.drop()
        objects.drop()
        relations.drop()
        object_relations.drop()

    request.addfinalizer(_drop_all)


def test_perf_post_refactor_route_handles_30_linked_objects_under_one_second(rest_api):
    """
    Sanity test: with 30 linked Neighbour objects each carrying a ref field, the route
    completes in well under a second. Pre-refactor, the per-call get_summary_line N+1
    pattern issued ~30 round trips for this dataset; the batched lookup collapses that
    to a single $in. We just pin a generous upper bound here so the test is stable
    """
    timings: list[float] = []

    for _ in range(5):
        start = time.perf_counter()
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_TARGET}&target_type=CHILD&with_root=true')
        elapsed = time.perf_counter() - start
        timings.append(elapsed)

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['children_nodes']) == N_LINKED

    median_seconds: float = median(timings)
    print(f"\n[ci_explorer perf] N_LINKED={N_LINKED} median={median_seconds*1000:.1f}ms "
          f"min={min(timings)*1000:.1f}ms max={max(timings)*1000:.1f}ms")
    assert median_seconds < 1.0, f"Route too slow: median={median_seconds:.3f}s"
