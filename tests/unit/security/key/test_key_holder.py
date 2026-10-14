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
import logging
from typing import Any

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.errors.database import DocumentGetError, DocumentNetworkError
from cmdb.errors.security import TokenKeyMaterialError
from cmdb.security.key import holder as holder_module
from cmdb.security.key.holder import (
    NO_STORED_KEY_HALF_MSG,
    NO_STORED_KEYPAIR_MSG,
    PRIVATE_HALF,
    PUBLIC_HALF,
    KeyHolder,
    clear_stored_keypair_cache,
    load_key_holder,
    read_stored_keypair,
)
from cmdb.security.key.secret_resolver import ASYMMETRIC_KEY_SETTING
from cmdb.security.key.security_settings import read_security_setting


class _CountingRead:
    """Wraps read_security_setting and counts the reads that actually reach the database."""

    def __init__(self) -> None:
        self.reads = 0

    def __call__(self, dbm: Any, database: str | None, key: str) -> Any:
        """Records the call and delegates."""
        self.reads += 1

        return read_security_setting(dbm, database, key)
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


class TestTheStoredKeypairIsReadOnce:
    """
    On-premise, both halves live in ONE settings document

    A holder that signs asks for both, so an uncached read cost two round trips to build one - and
    `TokenGenerator` calls `get_private_key()` again for every token it signs, which made it three per
    login. The keypair is written once when the database is created and never rotated, so a holder
    caches it for its own lifetime.
    """

    @staticmethod
    def _on_premise_app() -> BaseCmdbApp:
        """An on-premise app: the keys come from the stored security document"""
        app = BaseCmdbApp(__name__)
        app.cloud_mode = False
        app.local_mode = False
        return app

    def test_building_a_holder_reads_the_document_once(self, database_manager, monkeypatch) -> None:
        """Two keys, one read - counted where the read reaches the database, not inferred from the cache."""
        counter = _CountingRead()
        monkeypatch.setattr(holder_module, 'read_security_setting', counter)

        with self._on_premise_app().app_context():
            KeyHolder(database_manager)

        assert counter.reads == 1

    def test_a_later_key_access_reads_nothing(self, database_manager, monkeypatch) -> None:
        """What `TokenGenerator` does per token must not reach the database."""
        counter = _CountingRead()
        monkeypatch.setattr(holder_module, 'read_security_setting', counter)
        app = self._on_premise_app()

        with app.app_context():
            holder = KeyHolder(database_manager)

            before = counter.reads

            holder.get_private_key()
            holder.get_public_key()

        assert counter.reads == before

    def test_both_halves_are_the_stored_ones(self, database_manager) -> None:
        """The cache must not change which key is answered."""
        app = BaseCmdbApp(__name__)
        app.cloud_mode = False
        app.local_mode = False

        with app.app_context():
            holder = KeyHolder(database_manager)
            stored = read_security_setting(database_manager, None, ASYMMETRIC_KEY_SETTING)

            assert holder.get_public_key() == stored['public']
            assert holder.get_private_key() == stored['private']


class TestNoManagerIsHeld:
    """The holder reads the security document through security_settings and holds no SettingsManager"""

    def test_it_holds_no_settings_manager(self, database_manager) -> None:
        """A manager holds no other manager - and the holder is not even a manager"""
        app = BaseCmdbApp(__name__)
        app.cloud_mode = False
        app.local_mode = False

        with app.app_context():
            holder = KeyHolder(database_manager)

        assert not hasattr(holder, 'settings_manager')
        assert holder.dbm is database_manager


def _on_premise_app() -> BaseCmdbApp:
    """An on-premise app: the keys come from the stored security document"""
    app = BaseCmdbApp(__name__)
    app.cloud_mode = False
    app.local_mode = False

    return app


class TestAMissingStoredKeyIsNamed:
    """On premise, a keypair that is not there says so - not that None cannot be subscripted"""

    def test_no_stored_keypair(self, database_manager, monkeypatch) -> None:
        """No security document, or none holding the keypair"""
        monkeypatch.setattr(holder_module, 'read_security_setting', lambda *_: None)

        with _on_premise_app().app_context():
            with pytest.raises(ValueError, match=NO_STORED_KEYPAIR_MSG):
                KeyHolder(database_manager, with_private_key=False)

    def test_a_missing_half_is_named(self, database_manager, monkeypatch) -> None:
        """A keypair without the half asked for names the half"""
        monkeypatch.setattr(holder_module, 'read_security_setting', lambda *_: {'private': b'private'})

        with _on_premise_app().app_context():
            with pytest.raises(ValueError) as exc_info:
                KeyHolder(database_manager, with_private_key=False)

        assert str(exc_info.value) == NO_STORED_KEY_HALF_MSG.format(half=PUBLIC_HALF)

    def test_a_present_half_is_answered(self, database_manager, monkeypatch) -> None:
        """The checks change nothing for a complete keypair"""
        monkeypatch.setattr(holder_module, 'read_security_setting',
                            lambda *_: {'public': b'public', 'private': b'private'})

        with _on_premise_app().app_context():
            holder = KeyHolder(database_manager)

        assert (holder.rsa_public, holder.rsa_private) == (b'public', b'private')


class TestLoadKeyHolder:
    """The one way a signer or verifier gets a holder: a failure comes out typed, never raw"""

    def test_a_readable_key_is_a_holder(self, database_manager) -> None:
        """The ordinary case: the holder, built with the flag it was given"""
        with _on_premise_app().app_context():
            holder = load_key_holder(database_manager, with_private_key=False)

        assert isinstance(holder, KeyHolder)
        assert holder.rsa_public and holder.rsa_private is None

    def test_a_missing_key_is_key_material(self, database_manager, monkeypatch, caplog) -> None:
        """The server's fault (500), carrying the error itself and logged at ERROR once"""
        monkeypatch.setattr(holder_module, 'read_security_setting', lambda *_: None)
        caplog.set_level(logging.ERROR, logger=holder_module.LOGGER.name)

        with _on_premise_app().app_context():
            with pytest.raises(TokenKeyMaterialError) as exc_info:
                load_key_holder(database_manager)

        assert isinstance(exc_info.value.args[0], ValueError)
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert len([record for record in caplog.records if record.name == holder_module.LOGGER.name]) == 1

    def test_a_hosted_cloud_variable_problem_is_key_material(self, database_manager, monkeypatch) -> None:
        """An unset DG_RSA_PUBLIC_KEY is the same server-side fault"""
        monkeypatch.delenv('DG_RSA_PUBLIC_KEY', raising=False)

        with _cloud_app(local_mode=False).app_context():
            with pytest.raises(TokenKeyMaterialError):
                load_key_holder(database_manager, with_private_key=False)

    def test_an_outage_is_a_network_error(self, database_manager, monkeypatch) -> None:
        """
        A lost server, however wrapped, is a DocumentNetworkError - the app answers 503, try again

        Shaped as the read reports it: the manager's DocumentGetError over the driver's failure
        """
        def _lost(*_: Any) -> Any:
            try:
                raise ServerSelectionTimeoutError('no server')
            except ServerSelectionTimeoutError as err:
                raise DocumentGetError(err) from err

        monkeypatch.setattr(holder_module, 'read_security_setting', _lost)

        with _on_premise_app().app_context():
            with pytest.raises(DocumentNetworkError) as exc_info:
                load_key_holder(database_manager)

        assert isinstance(exc_info.value.__cause__, DocumentGetError)

    def test_an_ordinary_read_failure_is_key_material(self, database_manager, monkeypatch) -> None:
        """A read that failed for any other reason is not retryable - 500, not 503"""
        def _failed(*_: Any) -> Any:
            raise DocumentGetError('unreadable')

        monkeypatch.setattr(holder_module, 'read_security_setting', _failed)

        with _on_premise_app().app_context():
            with pytest.raises(TokenKeyMaterialError):
                load_key_holder(database_manager)


class _ScriptedRead:
    """Stands in for read_security_setting: answers the next scripted value per database, counting the reads"""

    def __init__(self, answers: dict[str, list[Any]]) -> None:
        self.answers: dict[str, list[Any]] = answers
        self.reads: list[str] = []

    def __call__(self, dbm: Any, database: str | None, key: str) -> Any:
        """Records which database was read and answers its next value"""
        del database, key
        self.reads.append(dbm.db_name)

        return self.answers[dbm.db_name].pop(0)


class _Dbm:
    """A database manager as far as the cache sees it: its default database's name"""

    def __init__(self, db_name: str) -> None:
        self.db_name: str = db_name


KEYPAIR: dict[str, bytes] = {PUBLIC_HALF: b'public', PRIVATE_HALF: b'private'}
OTHER_KEYPAIR: dict[str, bytes] = {PUBLIC_HALF: b'other-public', PRIVATE_HALF: b'other-private'}


class TestTheStoredKeypairIsReadOncePerProcess:
    """
    A complete keypair is read once per process and database - not once per holder, which was once per request

    The root conftest clears the cache around every test, so each starts with nothing read
    """

    def test_a_complete_keypair_is_read_once(self, monkeypatch) -> None:
        """Every later read - every later holder - is answered from memory"""
        read = _ScriptedRead({'db': [KEYPAIR]})
        monkeypatch.setattr(holder_module, 'read_security_setting', read)

        assert [read_stored_keypair(_Dbm('db')) for _ in range(3)] == [KEYPAIR] * 3
        assert read.reads == ['db']

    def test_each_holder_shares_the_one_read(self, monkeypatch) -> None:
        """What a request builds: a holder of its own - and no read of its own"""
        read = _ScriptedRead({'db': [KEYPAIR]})
        monkeypatch.setattr(holder_module, 'read_security_setting', read)

        with _on_premise_app().app_context():
            holders = [KeyHolder(_Dbm('db')) for _ in range(3)]

        assert {holder.rsa_public for holder in holders} == {KEYPAIR[PUBLIC_HALF]}
        assert len(read.reads) == 1

    @pytest.mark.parametrize('broken', [None, {PRIVATE_HALF: b'private'}, {PUBLIC_HALF: b'public'},
                                        {PUBLIC_HALF: None, PRIVATE_HALF: b'private'}, 'not a dict'],
                             ids=['none', 'no-public', 'no-private', 'null-public', 'not-a-dict'])
    def test_an_incomplete_keypair_is_not_kept(self, broken: Any, monkeypatch) -> None:
        """Read again next time - so a repaired keypair takes effect without a restart, then is kept"""
        read = _ScriptedRead({'db': [broken, KEYPAIR]})
        monkeypatch.setattr(holder_module, 'read_security_setting', read)

        assert read_stored_keypair(_Dbm('db')) == broken
        assert read_stored_keypair(_Dbm('db')) == KEYPAIR
        assert read_stored_keypair(_Dbm('db')) == KEYPAIR
        assert read.reads == ['db', 'db']

    def test_each_database_has_its_own_keypair(self, monkeypatch) -> None:
        """Keyed by the database read: another database is never answered this one's keypair"""
        read = _ScriptedRead({'db': [KEYPAIR], 'other': [OTHER_KEYPAIR]})
        monkeypatch.setattr(holder_module, 'read_security_setting', read)

        assert read_stored_keypair(_Dbm('db')) == KEYPAIR
        assert read_stored_keypair(_Dbm('other')) == OTHER_KEYPAIR
        assert read_stored_keypair(_Dbm('db')) == KEYPAIR
        assert read.reads == ['db', 'other']

    def test_clearing_reads_again(self, monkeypatch) -> None:
        """What the tests rely on between each other"""
        read = _ScriptedRead({'db': [KEYPAIR, OTHER_KEYPAIR]})
        monkeypatch.setattr(holder_module, 'read_security_setting', read)

        read_stored_keypair(_Dbm('db'))
        clear_stored_keypair_cache()

        assert read_stored_keypair(_Dbm('db')) == OTHER_KEYPAIR
        assert len(read.reads) == 2

    def test_the_cloud_modes_read_nothing(self, monkeypatch) -> None:
        """The cache is the on-premise source's: a developer cloud stack still answers the app's own keys"""
        read = _ScriptedRead({})
        monkeypatch.setattr(holder_module, 'read_security_setting', read)

        with _cloud_app(local_mode=True).app_context():
            KeyHolder(_Dbm('db'))

        assert not read.reads
