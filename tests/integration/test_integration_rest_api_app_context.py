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
Integration tests for the two app contexts every test runs in

The session-wide ``app_context`` is a bare BaseCmdbApp without a database manager - but only until the first request
through ``rest_api``, whose ``with``-opened client keeps the last request's context pushed. So which app ``current_app``
is without help depends on the tests that ran before. ``rest_api_app_context`` pushes the REST API app's context
whatever ran before, so ManagerProvider reaches the session's database. Pinned: the app it pushes, and that a manager
resolved inside it reads real documents
"""
# pylint: disable=protected-access  # Flask's _get_current_object is how a proxy is compared to an app
import pytest
from flask import current_app

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 97011
TYPE_NAME: str = 'app-context-probe'


@pytest.mark.usefixtures('rest_api_app_context')
def test_the_shared_fixture_pushes_the_rest_app(rest_api, database_manager: MongoDatabaseManager) -> None:
    """current_app is the REST app, carrying the session's database manager"""
    assert current_app._get_current_object() is rest_api.application
    assert current_app.database_manager is database_manager


@pytest.mark.usefixtures('rest_api_app_context')
def test_a_manager_resolved_inside_it_reads_the_database(database_manager: MongoDatabaseManager,
                                                         database_name: str, full_access_user) -> None:
    """What the fifteen modules that switch it on need it for"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    types.insert_one(make_type_doc(TYPE_ID, TYPE_NAME))

    try:
        manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, full_access_user)

        assert manager.get_one(TYPE_ID)['name'] == TYPE_NAME
    finally:
        types.delete_many({'public_id': TYPE_ID})
