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
Integration tests: a write the unique index refuses - a race the pre-check could not see - is the pre-check's 400

On a scratch database carrying the production indexes (the session database has none): a second field class under a
stored name, and a scope role renamed to another's name, reach the index; the managers' errors carry the duplicate
key cause, so the create and the update helpers answer the readable 400 instead of a 500
"""
from typing import Any, Iterator

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.manager import FieldClassesManager, ScopeRolesManager
from cmdb.models.access_model import CmdbFieldClass, CmdbScopeRole
from cmdb.models.access_model import HistoryKind
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.access_routes import access_routes_helper
from cmdb.interface.rest_api.routes.access_routes.access_routes_helper import create_response, update_response
from cmdb.interface.rest_api.routes.access_routes.access_history_helper import ChangeContext
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-access-race'
TAKEN: str = 'taken!'
CLASS: dict[str, Any] = {'name': 'compliance', 'label': 'Compliance', 'description': ''}
ADMIN: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True, group_ids=[1])


@pytest.fixture(autouse=True)
def fixture_no_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """No history read or written - a refused write records nothing anyway, and the race is the subject"""
    monkeypatch.setattr(access_routes_helper, 'concerned_groups', lambda *_args: set())
    monkeypatch.setattr(access_routes_helper, 'record_change', lambda *_args: None)


def _role(name: str) -> dict[str, Any]:
    """A role body"""
    return {'name': name, 'description': '', 'types': '*', 'operations': [], 'write_regular_fields': False,
            'field_classes': []}


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A scratch database booted once - the unique indexes exist"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    CollectionValidator(scratch, database_manager).init_management_collections()

    yield scratch

    client.drop_database(scratch)


def test_a_create_losing_the_race(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """The name was taken after the pre-check: 400 with the pre-check's message, one class stored"""
    manager = FieldClassesManager(database_manager, scratch)
    manager.insert_item(dict(CLASS))

    with pytest.raises(BadRequest) as raised:
        create_response(manager, CmdbFieldClass, dict(CLASS), TAKEN, ChangeContext(ADMIN, HistoryKind.FIELD_CLASS))

    assert raised.value.description == TAKEN
    assert manager.count_documents({}) == 1


def test_an_update_losing_the_race(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """A rename onto a name taken meanwhile: 400 with the pre-check's message, the role unchanged"""
    manager = ScopeRolesManager(database_manager, scratch)
    manager.insert_item(_role('first'))
    second: int = manager.insert_item(_role('second'))
    stored: dict[str, Any] = manager.get_item(second, as_dict=True)

    with pytest.raises(BadRequest) as raised:
        update_response(manager, CmdbScopeRole, second, _role('first'), TAKEN,
                        ChangeContext(ADMIN, HistoryKind.SCOPE_ROLE), stored)

    assert raised.value.description == TAKEN
    assert manager.get_item(second, as_dict=True)['name'] == 'second'
