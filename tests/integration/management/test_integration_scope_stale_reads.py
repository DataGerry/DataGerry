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
Integration tests against the test MongoDB: the conditional assignments are read as such, and the type import's
stale-scope check (``scope_field_change_blocker``, shared with the Type route) refuses a stored Type losing a compared
field
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import AccessAssignmentsManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.scope_compiler import ScopeMessage
from cmdb.interface.rest_api.routes.access_routes.access_scope_guard import scope_field_change_blocker
# -------------------------------------------------------------------------------------------------------------------- #

# ManagerProvider reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

TYPE_ID: int = 9971
ROLE_ID: int = 9972
CONDITIONAL_ID: int = 9973
UNCONDITIONAL_ID: int = 9974
ADMIN: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True, group_ids=[1])
SCOPE: list[dict[str, Any]] = [{'field': 'host', 'op': 'exists'}]


@pytest.fixture(autouse=True)
def fixture_seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A role on the Type, one conditional and one unconditional assignment of it"""
    database = database_manager.connector.client[database_name]
    database[CmdbScopeRole.COLLECTION].insert_one({'public_id': ROLE_ID, 'name': 'stale-reads', 'description': '',
                                                   'types': [TYPE_ID], 'operations': ['view'],
                                                   'write_regular_fields': False, 'field_classes': []})
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': CONDITIONAL_ID, 'group_id': 2, 'role_id': ROLE_ID, 'scope': SCOPE, 'description': ''},
        {'public_id': UNCONDITIONAL_ID, 'group_id': 1, 'role_id': ROLE_ID, 'scope': '*', 'description': ''},
    ])

    yield

    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def test_only_the_conditional_assignments_are_read(database_manager: MongoDatabaseManager) -> None:
    """The list scope, not '*'"""
    found = AccessAssignmentsManager(database_manager).conditional_assignments()

    assert [assignment['public_id'] for assignment in found] == [CONDITIONAL_ID]


def test_the_import_check_refuses_a_type_losing_a_compared_field() -> None:
    """The same blocker the Type route aborts with"""
    stored = CmdbType.from_data({'public_id': TYPE_ID, 'name': 'stale', 'label': 'S', 'author_id': 1,
                                 'fields': [{'type': 'text', 'name': 'host', 'label': 'H'}],
                                 'render_meta': {'sections': [{'type': 'section', 'name': 'm', 'label': 'M',
                                                               'fields': ['host']}]}})
    updated = CmdbType.from_data({**CmdbType.to_json(stored), 'fields': [],
                                  'render_meta': {'sections': [{'type': 'section', 'name': 'm', 'label': 'M',
                                                                'fields': []}]}})

    assert scope_field_change_blocker(ADMIN, stored, updated) == ScopeMessage.STALE_ON_TYPE.value.format(
        field='host', type_id=TYPE_ID, assignment_ids=[CONDITIONAL_ID])
