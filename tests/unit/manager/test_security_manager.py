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
Unit tests for SecurityManager.

Covers generate_hmac (determinism + shape with a stubbed key) and every branch of
get_symmetric_aes_key: cloud+local (app key), cloud non-local (env key + the missing-env ValueError),
and on-premise generate-on-absence (with a stubbed settings manager so the shared DB key is untouched).
"""
import base64
from unittest.mock import patch

import pytest

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.manager import security_manager as security_manager_module
from cmdb.manager.security_manager import SecurityManager
# -------------------------------------------------------------------------------------------------------------------- #

FIXED_KEY: bytes = b'0123456789abcdef0123456789abcdef'  # 32 bytes


@pytest.fixture(name='security_manager')
def fixture_security_manager(database_manager) -> SecurityManager:
    """A SecurityManager wired to the test database (DB is only touched via the on-premise branch)."""
    return SecurityManager(database_manager)


def _cloud_app(local_mode: bool) -> BaseCmdbApp:
    """Builds a BaseCmdbApp flagged for cloud mode with the given local_mode."""
    app = BaseCmdbApp(__name__)
    app.cloud_mode = True
    app.local_mode = local_mode
    return app


class TestGenerateHmac:
    """generate_hmac is deterministic and base64-shaped for a fixed key."""

    def test_deterministic_and_base64(self, security_manager: SecurityManager, monkeypatch) -> None:
        """The same input yields the same 32-byte (sha256) digest, base64-encoded."""
        monkeypatch.setattr(security_manager, 'get_symmetric_aes_key', lambda: FIXED_KEY)

        first = security_manager.generate_hmac('secret')
        second = security_manager.generate_hmac('secret')

        assert first == second
        assert len(base64.b64decode(first)) == 32

    def test_different_inputs_differ(self, security_manager: SecurityManager, monkeypatch) -> None:
        """Different inputs produce different hashes."""
        monkeypatch.setattr(security_manager, 'get_symmetric_aes_key', lambda: FIXED_KEY)

        assert security_manager.generate_hmac('a') != security_manager.generate_hmac('b')


class TestGetSymmetricAesKeyCloud:
    """get_symmetric_aes_key cloud branches."""

    def test_cloud_local_returns_app_key(self, security_manager: SecurityManager) -> None:
        """cloud + local mode returns the key carried on the app."""
        app = _cloud_app(local_mode=True)

        with app.app_context():
            assert security_manager.get_symmetric_aes_key() == app.symmetric_key

    def test_cloud_non_local_returns_env_key(self, security_manager: SecurityManager, monkeypatch) -> None:
        """cloud (non-local) decodes the base64 key from DG_SYMMETRIC_KEY."""
        monkeypatch.setenv('DG_SYMMETRIC_KEY', base64.b64encode(FIXED_KEY).decode('utf-8'))
        app = _cloud_app(local_mode=False)

        with app.app_context():
            assert security_manager.get_symmetric_aes_key() == FIXED_KEY

    def test_cloud_non_local_missing_env_raises(self, security_manager: SecurityManager, monkeypatch) -> None:
        """cloud (non-local) with no DG_SYMMETRIC_KEY raises ValueError (B2 regression)."""
        monkeypatch.delenv('DG_SYMMETRIC_KEY', raising=False)
        app = _cloud_app(local_mode=False)

        with app.app_context():
            with pytest.raises(ValueError):
                security_manager.get_symmetric_aes_key()


class TestGenerateSymmetricAesKey:
    """Minting a new AES key and storing it in the 'security' settings section."""

    def test_writes_a_32_byte_key_to_the_security_section(
            self, security_manager: SecurityManager, monkeypatch) -> None:
        """AES-256 needs exactly 32 bytes, and the section name is what get_symmetric_aes_key reads back"""
        written: dict = {}

        monkeypatch.setattr(
            security_manager_module, 'write_security_setting',
            lambda dbm, database, values: written.update({'dbm': dbm, 'database': database, 'values': values}),
        )

        security_manager.generate_symmetric_aes_key()

        assert written['dbm'] is security_manager.dbm
        assert written['database'] == security_manager.database
        assert len(written['values']['symmetric_aes_key']) == 32

    def test_each_call_mints_a_different_key(self, security_manager: SecurityManager, monkeypatch) -> None:
        """A deterministic 'random' key would make every installation's secrets interchangeable"""
        keys: list[bytes] = []

        monkeypatch.setattr(
            security_manager_module, 'write_security_setting',
            lambda _dbm, _database, values: keys.append(values['symmetric_aes_key']),
        )

        security_manager.generate_symmetric_aes_key()
        security_manager.generate_symmetric_aes_key()

        assert keys[0] != keys[1]


class TestGetSymmetricAesKeyOnPremise:
    """get_symmetric_aes_key on-premise generate-on-absence branch (the security-document read stubbed)."""

    def test_generates_when_absent(self, security_manager: SecurityManager, monkeypatch) -> None:
        """A missing stored key triggers generation, then the freshly stored key is returned."""
        values = [None, b'freshly-generated-key']
        generated = {'count': 0}

        monkeypatch.setattr(security_manager_module, 'read_security_setting',
                            lambda _dbm, _database, key: values.pop(0))
        monkeypatch.setattr(security_manager, 'generate_symmetric_aes_key',
                            lambda: generated.__setitem__('count', generated['count'] + 1))

        app = BaseCmdbApp(__name__)
        app.cloud_mode = False

        with app.app_context():
            assert security_manager.get_symmetric_aes_key() == b'freshly-generated-key'

        assert generated['count'] == 1


class TestNoManagerIsHeld:
    """The security document is read and written through security_settings; no SettingsManager is held"""

    def test_it_builds_and_holds_no_settings_manager(self, database_manager) -> None:
        """Constructing one never builds a SettingsManager"""
        with patch('cmdb.manager.system_manager.settings_manager.SettingsManager') as settings_cls:
            manager = SecurityManager(database_manager, 'tenant_db')

        settings_cls.assert_not_called()
        assert not hasattr(manager, 'settings_manager')
        assert manager.dbm is database_manager
        assert manager.database == 'tenant_db'

    def test_the_stored_key_is_read_from_its_own_database(self, database_manager, monkeypatch) -> None:
        """The database argument reaches the read - on premise it names the one database"""
        reads: list = []
        monkeypatch.setattr(security_manager_module, 'read_security_setting',
                            lambda dbm, database, key: reads.append((database, key)) or b'stored')
        app = BaseCmdbApp(__name__)
        app.cloud_mode = False

        with app.app_context():
            assert SecurityManager(database_manager, 'tenant_db').get_symmetric_aes_key() == b'stored'

        assert reads == [('tenant_db', 'symmetric_aes_key')]
