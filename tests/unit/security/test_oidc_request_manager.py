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
Unit tests for OidcRequestManager (requires the pytest MongoDB test instance)
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.oidc_request_manager import OidcRequestManager, OIDC_REQUEST_TTL_SECONDS
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(name='request_manager')
def fixture_request_manager(database_manager: MongoDatabaseManager, database_name: str):
    manager = OidcRequestManager(database_manager)
    collection = database_manager.get_collection(OidcRequestManager.COLLECTION, database_name)
    collection.delete_many({})
    yield manager
    collection.delete_many({})


class TestStoreConsume:
    def test_store_then_consume_returns_document(self, request_manager: OidcRequestManager):
        request_manager.store('state-1', 'nonce-1', 'http://localhost:4200')
        stored = request_manager.consume('state-1')

        assert stored is not None
        assert stored['nonce'] == 'nonce-1'
        assert stored['spa_origin'] == 'http://localhost:4200'

    def test_second_consume_is_none(self, request_manager: OidcRequestManager):
        request_manager.store('state-2', 'nonce-2', 'http://localhost:4200')
        assert request_manager.consume('state-2') is not None
        # single use / replay protection
        assert request_manager.consume('state-2') is None

    def test_unknown_state_is_none(self, request_manager: OidcRequestManager):
        assert request_manager.consume('does-not-exist') is None


class TestTtlIndex:
    def test_ttl_index_created(self, request_manager: OidcRequestManager,
                               database_manager: MongoDatabaseManager, database_name: str):
        collection = database_manager.get_collection(OidcRequestManager.COLLECTION, database_name)
        indexes = collection.index_information()

        assert 'created_at_ttl' in indexes
        assert indexes['created_at_ttl'].get('expireAfterSeconds') == OIDC_REQUEST_TTL_SECONDS
        assert OIDC_REQUEST_TTL_SECONDS == 600

    def test_state_unique_index(self, request_manager: OidcRequestManager,
                                database_manager: MongoDatabaseManager, database_name: str):
        collection = database_manager.get_collection(OidcRequestManager.COLLECTION, database_name)
        indexes = collection.index_information()

        assert 'state_unique' in indexes
        assert indexes['state_unique'].get('unique') is True
