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
Package-level fixtures for the ``/objects`` functional tests

Holds the one fixture every module in the package needs: the CmdbType the routes validate against.
It is module-scoped rather than session-scoped so each module still starts from a known collection,
and autouse because no test in the package can run without it
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from tests.functional.framework.objects.objects_route_helpers import ALL_OBJECT_IDS, TYPE_ID, type_doc
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.fixture(scope='module', autouse=True)
def _seed_type_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the CmdbType used by every test and removes the type + all test objects after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.insert_one(type_doc())
    yield
    types.delete_one({'public_id': TYPE_ID})
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
