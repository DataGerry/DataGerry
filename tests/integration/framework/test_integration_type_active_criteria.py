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
Integration tests for the type listing's ``active`` criteria against a real MongoDB

`types_helper.build_type_criteria` decides whether the ``?active=`` flag adds a condition. What only
a real query shows is the effect of that decision on the rows: a client condition asking for inactive
types returns them in both criteria shapes - a dict and a pipeline - and criteria that say nothing about
``active`` are still narrowed by the flag
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.type_model import CmdbType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import build_type_criteria
# -------------------------------------------------------------------------------------------------------------------- #

ACTIVE_TYPE_ID: int = 93971
INACTIVE_TYPE_ID: int = 93972
SEEDED_IDS: list[int] = [ACTIVE_TYPE_ID, INACTIVE_TYPE_ID]


def _type_document(public_id: int, active: bool) -> dict[str, Any]:
    """A field-less stored CmdbType."""
    return {
        'public_id': public_id, 'name': f'active-criteria-{public_id}', 'label': f'Active Criteria {public_id}',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': active, 'fields': [],
        'render_meta': {'icon': '', 'sections': [], 'summary': {'fields': []}},
        'acl': {'activated': False, 'groups': {'includes': None}}, 'version': '1.0.0',
    }


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one active and one inactive type; yields a TypesManager over the test database."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': SEEDED_IDS}})
    types.insert_many([_type_document(ACTIVE_TYPE_ID, True), _type_document(INACTIVE_TYPE_ID, False)])
    yield TypesManager(database_manager)
    types.delete_many({'public_id': {'$in': SEEDED_IDS}})


def _listed(types_manager: TypesManager, client_criteria: Any, active: bool) -> list[int]:
    """The seeded type ids the listing query answers for these criteria and flag."""
    result = types_manager.iterate(BuilderParameters(build_type_criteria(client_criteria, active)))

    return sorted(cmdb_type.public_id for cmdb_type in result.results if cmdb_type.public_id in SEEDED_IDS)


SEEDED: dict[str, Any] = {'public_id': {'$in': SEEDED_IDS}}


@pytest.mark.parametrize('client_criteria', [
    {**SEEDED, 'active': False},
    [{'$match': {**SEEDED, 'active': False}}],
], ids=['dict', 'pipeline'])
@pytest.mark.parametrize('active', [True, False], ids=['flag on', 'flag off'])
def test_a_client_condition_for_inactive_types_returns_them(types_manager: TypesManager, client_criteria: Any,
                                                            active: bool) -> None:
    """The client's own condition decides, in both shapes, whatever the flag says"""
    assert _listed(types_manager, client_criteria, active) == [INACTIVE_TYPE_ID]


@pytest.mark.parametrize('client_criteria', [SEEDED, [{'$match': SEEDED}]], ids=['dict', 'pipeline'])
def test_criteria_without_an_active_condition_are_narrowed_by_the_flag(types_manager: TypesManager,
                                                                       client_criteria: Any) -> None:
    """The flag still restricts to active types when the client said nothing about it"""
    assert _listed(types_manager, client_criteria, True) == [ACTIVE_TYPE_ID]
    assert _listed(types_manager, client_criteria, False) == SEEDED_IDS
