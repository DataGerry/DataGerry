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
Integration tests for cmdb.database.updater.versions.updater_20261120 against a real MongoDB

The retired person rights leave every group; every other right, the wider wildcards included, stays; a second run
changes nothing
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261120 import Update20261120
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261120'
GROUPS: str = 'management.groups'
SEEDED: list[dict[str, Any]] = [
    {'public_id': 1, 'name': 'admin', 'rights': ['base.*']},
    {'public_id': 2, 'name': 'mixed', 'rights': ['base.framework.object.view', 'base.user-management.person.view',
                                                 'base.user-management.personGroup.*', 'base.user-management.*']},
    {'public_id': 3, 'name': 'none', 'rights': []},
]


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A database with three groups, dropped before and after"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    client[scratch][GROUPS].insert_many([dict(group) for group in SEEDED])

    yield scratch

    client.drop_database(scratch)


def _rights(database_manager: MongoDatabaseManager, scratch: str) -> dict[int, list[str]]:
    """Every group's rights"""
    return {group['public_id']: group['rights'] for group in database_manager.connector.client[scratch][GROUPS].find()}


def test_the_person_rights_leave_and_the_rest_stays(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Twice: the second run changes nothing"""
    for _ in range(2):
        Update20261120(database_manager, scratch).start_update()

        assert _rights(database_manager, scratch) == {
            1: ['base.*'], 2: ['base.framework.object.view', 'base.user-management.*'], 3: [],
        }
