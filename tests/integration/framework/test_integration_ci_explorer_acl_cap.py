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
Integration tests for the CI Explorer's ACL-aware cap, against a real MongoDB and the real managers

What the unit tests cannot show: the up-front denied-types query, run by MongoDB, denies exactly the types the
per-object pass denies; each source's read, run by MongoDB with the type scope, leaves the unreadable neighbours
out before the cap - so the cap keeps the readable ones; and the whole graph under a cap answers the readable
neighbour, while a hidden target is refused before any source reads
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.ci_explorer.access import collect_denied_type_ids, load_denied_type_ids
from cmdb.framework.ci_explorer.context import CiExplorerGraphRequest, CiExplorerManagers
from cmdb.framework.ci_explorer.graph import build_ci_explorer_graph
from cmdb.framework.ci_explorer.locations import collect_location_children_objects
from cmdb.framework.ci_explorer.type_scope import NeighbourTypeScope
from cmdb.manager import LocationsManager, ObjectRelationsManager, ObjectsManager, RelationsManager, TypesManager
from cmdb.models.ci_explorer_model import NodeType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.errors.ci_explorer import CiExplorerTargetNotFoundError
from tests.utils import ci_explorer_acl_cap_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

ADMIN_ID: int = 1


@pytest.fixture(name='context')
def fixture_context(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """The seed, the request context the managers resolve in, and the suite's admin"""
    seed.seed(database_manager, database_name)
    admin = CmdbUser.from_data(
        database_manager.get_collection(CmdbUser.COLLECTION, database_name).find_one({'public_id': ADMIN_ID}))

    with rest_api.application.test_request_context():
        yield admin

    seed.purge(database_manager, database_name)


def _managers(database_manager: MongoDatabaseManager) -> CiExplorerManagers:
    """The real managers"""
    return CiExplorerManagers(
        objects=ObjectsManager(database_manager), types=TypesManager(database_manager),
        relations=RelationsManager(database_manager), object_relations=ObjectRelationsManager(database_manager),
        locations=LocationsManager(database_manager),
    )


class TestTheDeniedTypesQuery:
    """One projected query, the same rule as the per-object pass."""

    def test_it_denies_the_locked_type_and_not_the_open_one(self, database_manager, context: CmdbUser) -> None:
        """Even the admin: an activated ACL naming no group denies every group"""
        denied = load_denied_type_ids(TypesManager(database_manager), context)

        assert seed.LOCKED_TYPE_ID in denied and seed.OPEN_TYPE_ID not in denied

    def test_it_agrees_with_the_per_object_pass_on_every_stored_type(
            self, database_manager, database_name, context: CmdbUser) -> None:
        """Whatever types the database holds, both passes deny the same ones"""
        stored: dict[int, dict[str, Any]] = {
            document['public_id']: document
            for document in database_manager.get_collection(CmdbType.COLLECTION, database_name).find({})
        }

        assert load_denied_type_ids(TypesManager(database_manager), context) == \
            frozenset(collect_denied_type_ids(stored, context))


class TestEachSourceReadsReadableNeighboursOnly:
    """MongoDB applies the scope before the cap."""

    def test_the_location_children_cap_keeps_the_readable_child(self, database_manager, context: CmdbUser) -> None:
        """The two hidden children have the lowest ids; with them excluded in the read, a cap of 1 keeps the third"""
        scope = NeighbourTypeScope(denied=load_denied_type_ids(TypesManager(database_manager), context))

        children = collect_location_children_objects(
            {'public_id': seed.FOCAL_NODE_ID, 'parent': seed.ROOT_LOCATION_ID, 'object_id': seed.LOCATION_FOCAL_ID},
            scope, 1, True, LocationsManager(database_manager), ObjectsManager(database_manager),
        )

        assert [child['public_id'] for child in children] == [seed.LOCATION_READABLE_CHILD_ID]


class TestTheGraph:
    """The whole graph, through the real managers."""

    @pytest.mark.parametrize('item_limit', [1, 2])
    def test_a_capped_graph_answers_the_readable_neighbour(
            self, database_manager, context: CmdbUser, item_limit: int) -> None:
        """The relation source's two hidden neighbours sort first and take no slot"""
        request = CiExplorerGraphRequest(target_id=seed.FOCAL_ID, target_type=NodeType.CHILD, item_limit=item_limit)

        response = build_ci_explorer_graph(request, _managers(database_manager), context)

        assert [node['linked_object']['public_id'] for node in response['children_nodes']] == [seed.READABLE_ID]

    def test_a_hidden_target_is_refused(self, database_manager, context: CmdbUser) -> None:
        """The same error a missing object raises"""
        request = CiExplorerGraphRequest(target_id=seed.HIDDEN_FOCAL_ID, target_type=NodeType.BOTH, item_limit=1)

        with pytest.raises(CiExplorerTargetNotFoundError):
            build_ci_explorer_graph(request, _managers(database_manager), context)
