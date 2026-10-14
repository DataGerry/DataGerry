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
Integration tests for the key a TokenGenerator signs with, in hosted cloud mode against the real key ladder

The generator signs every token with the private key its holder loaded - and ``load_key_holder`` checked - when the
generator was built. It used to resolve the key again per token: in hosted cloud that re-read ``DG_RSA_PRIVATE_KEY``,
so a variable that changed or went away after construction failed the signing itself, with an untyped error. Here
the variable is removed after construction and the generator still signs a token the real validator accepts
"""
import base64

import pytest
from flask import Flask

from cmdb.database import MongoDatabaseManager
from cmdb.security.key.holder import PRIVATE_KEY_ENV_VAR, PUBLIC_KEY_ENV_VAR, KeyHolder
from cmdb.security.token.generator import TokenGenerator
from cmdb.security.token.token_constants import TokenClaim, TokenClaimWrapperKey
from cmdb.security.token.validator import TokenValidator
# -------------------------------------------------------------------------------------------------------------------- #

PAYLOAD: dict[str, dict[str, int]] = {'user': {'public_id': 1}}
TOKEN_COUNT: int = 2


def _app(cloud_mode: bool) -> Flask:
    """An app context in the given mode, never the developer cloud stack"""
    app = Flask(__name__)
    app.cloud_mode = cloud_mode
    app.local_mode = False

    return app


@pytest.fixture(name='hosted_cloud_keys')
def fixture_hosted_cloud_keys(database_manager: MongoDatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite's own keypair, exported into the two variables hosted cloud reads"""
    with _app(cloud_mode=False).app_context():
        holder = KeyHolder(database_manager)

    monkeypatch.setenv(PUBLIC_KEY_ENV_VAR, base64.b64encode(holder.rsa_public).decode('ascii'))
    monkeypatch.setenv(PRIVATE_KEY_ENV_VAR, base64.b64encode(holder.rsa_private).decode('ascii'))


@pytest.mark.usefixtures('hosted_cloud_keys')
def test_a_variable_removed_after_construction_does_not_fail_the_signing(
        database_manager: MongoDatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Built while the variable was there; every later token is signed with the key loaded then"""
    with _app(cloud_mode=True).app_context():
        generator = TokenGenerator(database_manager)
        validator = TokenValidator(database_manager)

        monkeypatch.delenv(PRIVATE_KEY_ENV_VAR)

        tokens: list[bytes] = [generator.generate_token(PAYLOAD) for _ in range(TOKEN_COUNT)]
        claims: list[dict] = [validator.decode_token(token) for token in tokens]

    assert all(claim[TokenClaim.DATAGERRY.value][TokenClaimWrapperKey.VALUE.value] == PAYLOAD for claim in claims)
