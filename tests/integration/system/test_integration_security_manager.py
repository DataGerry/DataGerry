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
Integration tests for SecurityManager against the real settings-backed key.

These are READ-ONLY on the 'security' section: the symmetric AES key seeded during session setup
backs every stored password (admin/admin), so the tests must not regenerate or delete it. They assert
the on-premise (non-cloud) key retrieval returns a stable key and that generate_hmac is deterministic
against it. The autouse app_context fixture provides a non-cloud current_app.
"""
import base64

import pytest

from cmdb.manager.security_manager import SecurityManager
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(name='security_manager')
def fixture_security_manager(database_manager, database_name) -> SecurityManager:
    """Provides a SecurityManager wired to the test database."""
    return SecurityManager(database_manager, database_name)


def test_returns_stored_key_and_is_stable(security_manager: SecurityManager) -> None:
    """The on-premise branch returns the session's stored key, identical across calls."""
    first = security_manager.get_symmetric_aes_key()
    second = security_manager.get_symmetric_aes_key()

    assert isinstance(first, bytes)
    assert first == second


def test_generate_hmac_is_deterministic_against_real_key(security_manager: SecurityManager) -> None:
    """Hashing the same value twice against the real key yields identical base64 output."""
    first = security_manager.generate_hmac('admin')
    second = security_manager.generate_hmac('admin')

    assert first == second
    assert len(base64.b64decode(first)) == 32
