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
Integration tests for an on-premise installation whose RSA keypair is not stored, against a real MongoDB

Nothing is patched: a second database manager is bound to a throwaway database, and the real settings read finds
no keypair there (or one without its public half). The holder names what is missing, and the validator and the
generator - which read the key when they are built - raise the typed ``TokenKeyMaterialError`` the routes answer
500, not the raw error a route's catch-all answered 401. The suite's own database, which has its keypair, is the
control - and is read once however many holders are built, while the keyless database beside it is never answered
the suite's cached keypair
"""
from typing import Any

import pytest
from flask import Flask

from cmdb.database import MongoDatabaseManager
from cmdb.security.key import holder as holder_module
from cmdb.security.key.holder import NO_STORED_KEY_HALF_MSG, NO_STORED_KEYPAIR_MSG, PUBLIC_HALF, load_key_holder
from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY
from cmdb.security.key.secret_resolver import ASYMMETRIC_KEY_SETTING, SECURITY_SECTION
from cmdb.security.key.security_settings import SETTINGS_COLLECTION, read_security_setting
from cmdb.security.token.generator import TokenGenerator
from cmdb.security.token.validator import TokenValidator

from cmdb.errors.security import TokenKeyMaterialError
# -------------------------------------------------------------------------------------------------------------------- #

KEYLESS_DATABASE: str = 'cmdb-test-keyless'
HOLDER_COUNT: int = 4


def _on_premise_app() -> Flask:
    """An on-premise app context: the key comes from the stored security document"""
    app = Flask(__name__)
    app.cloud_mode = False
    app.local_mode = False

    return app


@pytest.fixture(name='keyless_dbm')
def fixture_keyless_dbm(mongodb_parameters: tuple):
    """A database manager bound to a throwaway database with no security document; dropped afterwards"""
    host, port, _database = mongodb_parameters
    dbm = MongoDatabaseManager(host, port, KEYLESS_DATABASE)
    dbm.connector.client.drop_database(KEYLESS_DATABASE)

    yield dbm

    dbm.connector.client.drop_database(KEYLESS_DATABASE)


def _store_security(dbm: MongoDatabaseManager, values: dict[str, Any]) -> None:
    """Writes the security settings document of the throwaway database"""
    dbm.connector.client[KEYLESS_DATABASE][SETTINGS_COLLECTION].insert_one(
        {SETTINGS_SECTION_ID_KEY: SECURITY_SECTION, **values},
    )


def test_no_stored_keypair_is_named_and_typed(keyless_dbm: MongoDatabaseManager) -> None:
    """No security document at all: the typed error, carrying the named reason"""
    with _on_premise_app().app_context():
        with pytest.raises(TokenKeyMaterialError) as exc_info:
            load_key_holder(keyless_dbm)

    assert str(exc_info.value.args[0]) == NO_STORED_KEYPAIR_MSG


def test_a_keypair_without_its_public_half_is_named(keyless_dbm: MongoDatabaseManager) -> None:
    """A security document whose keypair lacks the half the validator needs"""
    _store_security(keyless_dbm, {ASYMMETRIC_KEY_SETTING: {'private': b'private'}})

    with _on_premise_app().app_context():
        with pytest.raises(TokenKeyMaterialError) as exc_info:
            load_key_holder(keyless_dbm, with_private_key=False)

    assert str(exc_info.value.args[0]) == NO_STORED_KEY_HALF_MSG.format(half=PUBLIC_HALF)


@pytest.mark.parametrize('build', [TokenValidator, TokenGenerator], ids=['validator', 'generator'])
def test_the_signer_and_the_verifier_raise_the_typed_error(keyless_dbm: MongoDatabaseManager, build: Any) -> None:
    """Both read the key when built - a raw error there was a 401"""
    with _on_premise_app().app_context():
        with pytest.raises(TokenKeyMaterialError):
            build(keyless_dbm)


def test_the_suites_own_database_still_loads(database_manager: MongoDatabaseManager) -> None:
    """The control: a stored keypair loads, both halves"""
    with _on_premise_app().app_context():
        holder = load_key_holder(database_manager)

    assert holder.rsa_public and holder.rsa_private


def test_the_stored_keypair_is_read_once_for_many_holders(database_manager: MongoDatabaseManager, monkeypatch) -> None:
    """The real settings read, counted: one read, however many holders - what a request each used to cost"""
    reads: list[str] = []

    def _counting(dbm: MongoDatabaseManager, database: str | None, key: str) -> Any:
        reads.append(dbm.db_name)

        return read_security_setting(dbm, database, key)

    monkeypatch.setattr(holder_module, 'read_security_setting', _counting)

    with _on_premise_app().app_context():
        publics = {load_key_holder(database_manager).rsa_public for _ in range(HOLDER_COUNT)}

    assert len(publics) == 1
    assert reads == [database_manager.db_name]


def test_a_cached_keypair_is_not_another_databases(
        database_manager: MongoDatabaseManager, keyless_dbm: MongoDatabaseManager) -> None:
    """The suite's keypair is in memory; the keyless database beside it still has none"""
    with _on_premise_app().app_context():
        load_key_holder(database_manager)

        with pytest.raises(TokenKeyMaterialError):
            load_key_holder(keyless_dbm)
