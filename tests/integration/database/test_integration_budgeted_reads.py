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
Integration tests: four reads whose later batches ran on after the socket gave up now carry a server-side budget

A read without ``maxTimeMS`` is bounded only by the driver's socket timeout, which stops the command in flight but
not a ``getMore`` - the server finishes that batch for nobody. These reads stream per-document work across batches,
so each now runs through ``aggregate_within_time_limit``:

    - the search's reference pre-query (``collect_referenced_match_ids``) - REALLY stopped here: a costly condition
      over many objects and a tiny budget, and the server ends it with the typed time-limit error
    - the location tree search, the MDS half of the reference listing and the IPAM subnet's assigned rows - run
      against MongoDB through a spy on the database layer, which pins the budget each one hands to the server and
      that the read still answers what it did
"""
import time
from ipaddress import IPv4Network
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import LONG_QUERY_TIME_LIMIT_MS, QUERY_TIME_LIMIT_MS
from cmdb.framework.ipam.subnet_overview.assigned_rows import load_assigned_rows_map
from cmdb.framework.search.search_reference_match import collect_referenced_match_ids
from cmdb.manager.locations_manager import LocationsManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.utils import find_cause
from cmdb.errors.database import DocumentQueryTimeLimitError
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from tests.utils.ipam_doc_builders import make_object_doc
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_OBJECT_ID: int = 93100
# Many documents, each costly: the server checks the budget between documents, so it is the count that lets it stop
OBJECT_COUNT: int = 1000
PROBE_TYPE_ID: int = 93099
# Each document's $reduce walks this many numbers - a few ms of server CPU per document, seconds for them all
BURN_LENGTH: int = 30000
# Far below what the burn costs
BUDGET_MS: int = 200
# A stopped read ends long before the whole burn would; generous for a loaded machine
STOPPED_WITHIN_S: float = 2.0

LOCATION_ID: int = 93150
LOCATION_NAME: str = 'budgeted-read-probe-node'
SUBNET_OBJECT_ID: int = 93160
SUBNET_NETWORK: IPv4Network = IPv4Network('10.93.0.0/24')


def _burning_condition() -> dict[str, Any]:
    """A $match condition that costs server CPU per document and is never constant-folded"""
    return {'$expr': {'$gte': [{'$reduce': {
        'input': {'$range': [0, {'$add': [BURN_LENGTH, '$public_id']}]},
        'initialValue': 0,
        'in': {'$add': ['$$value', '$$this']},
    }}, 0]}}


@pytest.fixture(name='budget_spy')
def fixture_budget_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Records (collection, budget) of every budgeted aggregation and lets it run against MongoDB"""
    calls: list[tuple[str, int]] = []
    real = MongoDatabaseManager.aggregate_within_time_limit

    def _spy(self: MongoDatabaseManager, collection: str, db_name: str, pipeline: list[dict[str, Any]],
             time_limit_ms: int, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append((collection, time_limit_ms))
        return real(self, collection, db_name, pipeline, time_limit_ms, **kwargs)

    monkeypatch.setattr(MongoDatabaseManager, 'aggregate_within_time_limit', _spy)

    return calls


@pytest.fixture(name='probe_objects')
def fixture_probe_objects(database_manager: MongoDatabaseManager, database_name: str):
    """OBJECT_COUNT plain objects of one probe type, removed afterwards"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ids: list[int] = list(range(FIRST_OBJECT_ID, FIRST_OBJECT_ID + OBJECT_COUNT))
    objects.delete_many({'public_id': {'$in': ids}})
    objects.insert_many([make_object_doc(public_id, PROBE_TYPE_ID, []) for public_id in ids])

    yield ids

    objects.delete_many({'public_id': {'$in': ids}})


class TestTheSearchsReferencePreQuery:
    """The pre-query runs before the budgeted search; it has a budget of its own"""

    def test_a_costly_term_is_stopped_on_the_budget(self, database_manager: MongoDatabaseManager,
                                                    database_name: str, probe_objects: list[int]) -> None:
        """The server ends it with the typed time-limit error, long before the whole burn"""
        objects_manager = ObjectsManager(database_manager, database_name)
        condition: dict[str, Any] = {'public_id': {'$in': probe_objects}, **_burning_condition()}
        started: float = time.monotonic()

        with pytest.raises(ObjectsManagerIterationError) as exc_info:
            collect_referenced_match_ids(objects_manager, condition, [], time_limit_ms=BUDGET_MS)

        timeout = find_cause(exc_info.value, DocumentQueryTimeLimitError)
        assert timeout is not None and timeout.time_limit_ms == BUDGET_MS
        assert time.monotonic() - started < STOPPED_WITHIN_S

    def test_a_plain_term_still_answers_its_ids_under_the_default(
            self, database_manager: MongoDatabaseManager, database_name: str, probe_objects: list[int],
            budget_spy: list[tuple[str, int]]) -> None:
        """The control: the default budget reaches the server, and the read answers what it matches"""
        objects_manager = ObjectsManager(database_manager, database_name)
        wanted: list[int] = probe_objects[:3]

        found = collect_referenced_match_ids(objects_manager, {'public_id': {'$in': wanted}}, [])

        assert sorted(found) == wanted
        assert budget_spy == [(CmdbObject.COLLECTION, QUERY_TIME_LIMIT_MS)]


class TestTheLocationTreeSearch:
    """The client's term on a collection scan, then a $graphLookup per match"""

    @pytest.fixture(autouse=True)
    def _node(self, database_manager: MongoDatabaseManager, database_name: str):
        """One location under the root, named so only it matches"""
        nodes = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        nodes.delete_many({'public_id': LOCATION_ID})
        nodes.insert_one({'public_id': LOCATION_ID, 'name': LOCATION_NAME, 'parent': RootLocationDefault.PUBLIC_ID,
                          'object_id': FIRST_OBJECT_ID, 'type_id': PROBE_TYPE_ID, 'type_label': 'Probe',
                          'type_icon': 'fas fa-cube', 'type_selectable': True})
        yield
        nodes.delete_many({'public_id': LOCATION_ID})

    def test_it_runs_under_the_query_budget_and_still_finds_the_node(
            self, database_manager: MongoDatabaseManager, database_name: str,
            budget_spy: list[tuple[str, int]]) -> None:
        """One budgeted read of the locations; the match comes back"""
        found = LocationsManager(database_manager, database_name).search_locations_with_ancestors(LOCATION_NAME)

        assert [node['public_id'] for node in found] == [LOCATION_ID]
        assert budget_spy == [(CmdbLocation.COLLECTION, QUERY_TIME_LIMIT_MS)]


class TestTheMdsHalfOfTheReferenceListing:
    """A $lookup into the objects per Type, batch by batch"""

    def test_it_runs_on_the_types_under_the_given_budget(
            self, database_manager: MongoDatabaseManager, database_name: str, probe_objects: list[int],
            budget_spy: list[tuple[str, int]]) -> None:
        """Against the types collection, with the budget the listing hands it; nothing references a probe"""
        objects_manager = ObjectsManager(database_manager, database_name)
        referenced: CmdbObject = CmdbObject.from_data(
            database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
                {'public_id': probe_objects[0]}, {'_id': 0}))

        rows = objects_manager.get_mds_references_for_object(referenced, None, BUDGET_MS)

        assert not rows
        assert (CmdbType.COLLECTION, BUDGET_MS) in budget_spy


class TestTheSubnetsAssignedRows:
    """Every stage streams, one row per interface row in the subnet"""

    def test_it_runs_under_the_long_budget(self, database_manager: MongoDatabaseManager, database_name: str,
                                           budget_spy: list[tuple[str, int]]) -> None:
        """An overview may legitimately take long - the long budget, against the objects"""
        rows = load_assigned_rows_map(ObjectsManager(database_manager, database_name), SUBNET_OBJECT_ID,
                                      SUBNET_NETWORK)

        assert not rows
        assert budget_spy == [(CmdbObject.COLLECTION, LONG_QUERY_TIME_LIMIT_MS)]
