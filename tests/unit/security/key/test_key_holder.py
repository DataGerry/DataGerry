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
Unit tests for KeyHolder RSA key resolution in cloud mode.

Covers the cloud+local branch (dev keys on the app), the cloud non-local branch (base64 key from the
env var), and the missing-env ValueError for both get_public_key and get_private_key (the fix for the
bug where base64.b64decode(os.getenv(...)) crashed on a missing env var and only logged on an empty one).
The KeyHolder is constructed under a cloud+local context so its eager __init__ needs no database.
"""
import base64

import pytest

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.security.key.holder import KeyHolder
# -------------------------------------------------------------------------------------------------------------------- #


def _cloud_app(local_mode: bool) -> BaseCmdbApp:
    """Builds a BaseCmdbApp flagged for cloud mode with the given local_mode."""
    app = BaseCmdbApp(__name__)
    app.cloud_mode = True
    app.local_mode = local_mode
    return app


@pytest.fixture(name='key_holder')
def fixture_key_holder(database_manager) -> KeyHolder:
    """A KeyHolder built under a cloud+local context so __init__ reads the app keys (no DB access)."""
    app = _cloud_app(local_mode=True)

    with app.app_context():
        return KeyHolder(database_manager)


class TestCloudLocal:
    """cloud + local mode returns the dev keys carried on the app."""

    def test_public_and_private_from_app(self, key_holder: KeyHolder) -> None:
        """Both keys come from current_app.asymmetric_key."""
        app = _cloud_app(local_mode=True)

        with app.app_context():
            assert key_holder.get_public_key() == app.asymmetric_key['public']
            assert key_holder.get_private_key() == app.asymmetric_key['private']


class TestCloudNonLocalEnv:
    """cloud (non-local) decodes the base64 keys from the environment."""

    def test_public_from_env(self, key_holder: KeyHolder, monkeypatch) -> None:
        """get_public_key decodes DG_RSA_PUBLIC_KEY."""
        monkeypatch.setenv('DG_RSA_PUBLIC_KEY', base64.b64encode(b'public-key-bytes').decode('utf-8'))
        app = _cloud_app(local_mode=False)

        with app.app_context():
            assert key_holder.get_public_key() == b'public-key-bytes'

    def test_private_from_env(self, key_holder: KeyHolder, monkeypatch) -> None:
        """get_private_key decodes DG_RSA_PRIVATE_KEY."""
        monkeypatch.setenv('DG_RSA_PRIVATE_KEY', base64.b64encode(b'private-key-bytes').decode('utf-8'))
        app = _cloud_app(local_mode=False)

        with app.app_context():
            assert key_holder.get_private_key() == b'private-key-bytes'


class TestCloudNonLocalMissingEnv:
    """cloud (non-local) with no env var raises ValueError instead of crashing/returning an empty key."""

    def test_public_missing_env_raises(self, key_holder: KeyHolder, monkeypatch) -> None:
        """A missing DG_RSA_PUBLIC_KEY raises ValueError (regression)."""
        monkeypatch.delenv('DG_RSA_PUBLIC_KEY', raising=False)
        app = _cloud_app(local_mode=False)

        with app.app_context():
            with pytest.raises(ValueError):
                key_holder.get_public_key()

    def test_private_missing_env_raises(self, key_holder: KeyHolder, monkeypatch) -> None:
        """A missing DG_RSA_PRIVATE_KEY raises ValueError (regression)."""
        monkeypatch.delenv('DG_RSA_PRIVATE_KEY', raising=False)
        app = _cloud_app(local_mode=False)

        with app.app_context():
            with pytest.raises(ValueError):
                key_holder.get_private_key()
