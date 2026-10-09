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
The session database has the shape a production boot gives it, where the suites depend on it

The session never runs `CollectionValidator`, so `conftest.preset_database` seeds the one piece of predefined data
the location tree relies on: the root CmdbLocation and a public_id counter past it. Without them the first node a
test created took public_id 1 - the root's id - and a member stored under it read as a top-level location, while
a test comparing the two ids passed by coincidence
"""
from cmdb.database import MongoDatabaseManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
# -------------------------------------------------------------------------------------------------------------------- #


def test_the_root_location_is_seeded(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Exactly one document carries the root id, and it is the synthetic root"""
    roots = list(database_manager.get_collection(CmdbLocation.COLLECTION, database_name).find(
        {'public_id': RootLocationDefault.PUBLIC_ID}))

    assert len(roots) == 1
    assert roots[0]['object_id'] == RootLocationDefault.NO_OBJECT


def test_a_new_location_never_takes_the_root_id(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The counter is past the root"""
    assert database_manager.get_next_public_id(CmdbLocation.COLLECTION, database_name) > RootLocationDefault.PUBLIC_ID
