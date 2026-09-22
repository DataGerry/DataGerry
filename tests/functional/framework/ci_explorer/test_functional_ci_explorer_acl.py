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
Object-ACL filtering of GET /ci_explorer/items

Without the object ACL, holding the ciExplorer.view right would be enough to read the label, type
and neighbourhood of any object in the database. These tests drive the real route against real
documents, which is the only way to prove it does not - the decision depends on an ACL stored on a
CmdbType, and a mock-based test would only assert the filter against itself.

The locked type carries an activated ACL that names no group, so it denies every user including the
suite's admin: access control fails closed, and no right bypasses it.

Two behaviours are pinned that a reader could reasonably expect to be different:

  - a denied neighbour is omitted with no trace at all - no placeholder, no count, nothing that
    distinguishes it from a neighbour that does not exist
  - a denied focal object answers **404**, the same answer a target that was never created gets,
    because a 403 would confirm that it exists
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database.mongo_connector import MongoConnector
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ci_explorer/items'

# Type ids
TYPE_OPEN: int = 8010            # no ACL at all - the ordinary case
TYPE_DEACTIVATED: int = 8011     # an ACL that is present but switched off
TYPE_LOCKED: int = 8012          # an activated ACL naming no group: denies everyone

# Object ids
OBJ_FOCAL: int = 8100            # of TYPE_OPEN, the focal object of most tests
OBJ_NEIGHBOUR_OPEN: int = 8101   # of TYPE_OPEN, must always be visible
OBJ_NEIGHBOUR_OFF: int = 8102    # of TYPE_DEACTIVATED, must always be visible
OBJ_NEIGHBOUR_LOCKED: int = 8103  # of TYPE_LOCKED, must never be visible
OBJ_FOCAL_LOCKED: int = 8104     # of TYPE_LOCKED, used as a focal object

# Relation + objectRelation ids
RELATION_LINKED: int = 8500
OBJ_REL_TO_OPEN: int = 8600
OBJ_REL_TO_OFF: int = 8601
OBJ_REL_TO_LOCKED: int = 8602
OBJ_REL_LOCKED_TO_OPEN: int = 8603

DEACTIVATED_ACL: dict[str, Any] = {'activated': False, 'groups': {'includes': {}}}
LOCKED_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {}}}


def _make_type(public_id: int, name: str, acl: dict[str, Any] | None) -> dict[str, Any]:
    """Builds a CmdbType; acl of None omits the key entirely, as a pre-ACL type would."""
    type_document: dict[str, Any] = {
        'public_id': public_id,
        'name': name,
        'label': name.title(),
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': 'name', 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-server',
            'sections': [],
            'summary': {'fields': ['name']},
        },
        'ci_explorer_label': 'name',
        'ci_explorer_color': '#1f77b4',
        'version': '1.0.0',
    }

    if acl is not None:
        type_document['acl'] = acl

    return type_document


def _make_object(public_id: int, type_id: int, display_name: str) -> dict[str, Any]:
    """Builds a CmdbObject with the one field the CI Explorer renders as its title."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'status': True,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'name': 'name', 'value': display_name}],
    }


def _make_object_relation(public_id: int, parent_id: int, parent_type_id: int,
                          child_id: int, child_type_id: int) -> dict[str, Any]:
    """Builds one objectRelation linking parent_id -> child_id."""
    return {
        'public_id': public_id,
        'relation_id': RELATION_LINKED,
        'relation_parent_id': parent_id,
        'relation_parent_type_id': parent_type_id,
        'relation_child_id': child_id,
        'relation_child_type_id': child_type_id,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'last_edit_time': None,
        'field_values': [],
    }


@pytest.fixture(scope='module', name='connector')
def fixture_connector(database_manager) -> MongoConnector:
    """Shortcut to the underlying MongoConnector for direct collection access."""
    return database_manager.connector


@pytest.fixture(scope='module', autouse=True)
def setup_acl_fixture(request, connector: MongoConnector, database_name):
    """Seeds three types of differing ACL state, their objects and the relations between them."""
    database = connector.client.get_database(database_name)
    types = database.get_collection(CmdbType.COLLECTION)
    objects = database.get_collection(CmdbObject.COLLECTION)
    relations = database.get_collection(CmdbRelation.COLLECTION)
    object_relations = database.get_collection(CmdbObjectRelation.COLLECTION)

    types.insert_many([
        _make_type(TYPE_OPEN, 'acl_open', None),
        _make_type(TYPE_DEACTIVATED, 'acl_off', DEACTIVATED_ACL),
        _make_type(TYPE_LOCKED, 'acl_locked', LOCKED_ACL),
    ])

    objects.insert_many([
        _make_object(OBJ_FOCAL, TYPE_OPEN, 'focal'),
        _make_object(OBJ_NEIGHBOUR_OPEN, TYPE_OPEN, 'neighbour-open'),
        _make_object(OBJ_NEIGHBOUR_OFF, TYPE_DEACTIVATED, 'neighbour-acl-off'),
        _make_object(OBJ_NEIGHBOUR_LOCKED, TYPE_LOCKED, 'neighbour-locked'),
        _make_object(OBJ_FOCAL_LOCKED, TYPE_LOCKED, 'focal-locked'),
    ])

    relations.insert_one({
        'public_id': RELATION_LINKED,
        'relation_name': 'linked',
        'parent_type_ids': [TYPE_OPEN, TYPE_LOCKED],
        'child_type_ids': [TYPE_OPEN, TYPE_DEACTIVATED, TYPE_LOCKED],
        'relation_name_parent': 'links',
        'relation_name_child': 'linked_by',
        'relation_icon_parent': 'fa-arrow-right',
        'relation_icon_child': 'fa-arrow-left',
        'relation_color_parent': '#33aa33',
        'relation_color_child': '#aa3333',
        'description': 'acl fixture relation',
        'sections': [],
        'fields': [],
    })

    object_relations.insert_many([
        _make_object_relation(OBJ_REL_TO_OPEN, OBJ_FOCAL, TYPE_OPEN, OBJ_NEIGHBOUR_OPEN, TYPE_OPEN),
        _make_object_relation(OBJ_REL_TO_OFF, OBJ_FOCAL, TYPE_OPEN, OBJ_NEIGHBOUR_OFF, TYPE_DEACTIVATED),
        _make_object_relation(OBJ_REL_TO_LOCKED, OBJ_FOCAL, TYPE_OPEN, OBJ_NEIGHBOUR_LOCKED, TYPE_LOCKED),
        _make_object_relation(
            OBJ_REL_LOCKED_TO_OPEN, OBJ_FOCAL_LOCKED, TYPE_LOCKED, OBJ_NEIGHBOUR_OPEN, TYPE_OPEN,
        ),
    ])

    def _drop_all() -> None:
        types.drop()
        objects.drop()
        relations.drop()
        object_relations.drop()

    request.addfinalizer(_drop_all)


def _child_ids(body: dict[str, Any]) -> set[int]:
    """The public_ids in the children bucket of a response body."""
    return {node['linked_object']['public_id'] for node in body['children_nodes']}


class TestDeniedNeighbours:
    """What a user may not read must not be in the payload."""

    def test_a_neighbour_of_a_locked_type_is_omitted(self, rest_api) -> None:
        """Without the filter the graph hands it over with its label and type."""
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_FOCAL}&target_type=CHILD')

        assert response.status_code == HTTPStatus.OK
        assert OBJ_NEIGHBOUR_LOCKED not in _child_ids(response.get_json())

    def test_the_readable_neighbours_are_untouched(self, rest_api) -> None:
        """A type with no ACL and one whose ACL is switched off are both open."""
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_FOCAL}&target_type=CHILD')

        assert _child_ids(response.get_json()) == {OBJ_NEIGHBOUR_OPEN, OBJ_NEIGHBOUR_OFF}

    def test_the_edge_of_a_denied_neighbour_is_omitted_too(self, rest_api) -> None:
        """An edge whose far end is not in the payload would draw a line to nothing."""
        body = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_FOCAL}&target_type=CHILD').get_json()

        edge_targets = {edge['to'] for edge in body['child_edges']}

        assert OBJ_NEIGHBOUR_LOCKED not in edge_targets
        assert edge_targets == {OBJ_NEIGHBOUR_OPEN, OBJ_NEIGHBOUR_OFF}

    def test_nothing_reports_that_something_was_hidden(self, rest_api) -> None:
        """
        No placeholder node and no count

        A response that said "1 neighbour hidden" would leak exactly what the ACL protects: that the
        object exists at all.
        """
        body = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_FOCAL}&target_type=CHILD').get_json()

        assert set(body) == {'children_nodes', 'child_edges'}
        assert len(body['children_nodes']) == len(body['child_edges']) == 2


class TestADeniedFocalObject:
    """The target itself is checked, and the refusal is indistinguishable from a missing object."""

    def test_a_denied_target_is_a_404(self, rest_api) -> None:
        """A 403 would confirm the object exists."""
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_FOCAL_LOCKED}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_a_missing_target_answers_the_same_way(self, rest_api) -> None:
        """The two must be indistinguishable, status and body alike."""
        denied = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_FOCAL_LOCKED}')
        missing = rest_api.get(f'{ROUTE_URL}?target_id=8999')

        assert denied.status_code == missing.status_code == HTTPStatus.NOT_FOUND

    def test_a_denied_target_leaks_no_neighbourhood(self, rest_api) -> None:
        """It has a readable neighbour; the refusal must not be a partial answer."""
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_FOCAL_LOCKED}&with_root=true')

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert 'root_node' not in (response.get_json() or {})


class TestAnOpenGraphIsUnaffected:
    """The common case - no type in scope carries an activated ACL - behaves as it always did."""

    def test_the_root_node_of_an_open_type_is_still_returned(self, rest_api) -> None:
        """The filter must not cost a user anything they were always allowed to see."""
        body = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_FOCAL}&with_root=true').get_json()

        assert body['root_node']['linked_object']['public_id'] == OBJ_FOCAL
        assert body['root_node']['title'] == 'focal'
