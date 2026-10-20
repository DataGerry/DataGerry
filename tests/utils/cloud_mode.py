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
Drives the REST test app as a hosted-cloud deployment

Two things differ from the on-premise app the test client normally talks to. Hosted cloud mode reads
the RSA keypair from the ``DG_RSA_*`` environment variables instead of the settings collection, so
the test database's own keypair is exported there. And a cloud token names the tenant database next
to the user id - the default test client's token does not - so a request resolves its user in that
tenant. ``enable_hosted_cloud_mode`` does the first, ``cloud_auth_header`` builds the second
"""
import base64
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.security.key.holder import KeyHolder, PUBLIC_KEY_ENV_VAR, PRIVATE_KEY_ENV_VAR
# -------------------------------------------------------------------------------------------------------------------- #

AUTHORIZATION_ENVIRON_KEY: str = 'HTTP_AUTHORIZATION'


def enable_hosted_cloud_mode(rest_api: Any, monkeypatch: Any, database_manager: MongoDatabaseManager) -> None:
    """
    Switches the app into hosted cloud mode for the duration of one test

    The keypair is read while the app is still on-premise (from the settings collection), then
    exported as Base64 into the environment variables hosted cloud mode reads, and only then is the
    cloud flag set - so tokens minted before and after the switch verify alike

    Args:
        rest_api (Any): The REST test client
        monkeypatch (Any): pytest's monkeypatch, which restores the flag and the variables afterwards
        database_manager (MongoDatabaseManager): The test database manager holding the keypair
    """
    with rest_api.application.app_context():
        holder = KeyHolder(database_manager)
        keys: dict[str, bytes] = {
            PUBLIC_KEY_ENV_VAR: holder.get_public_key(),
            PRIVATE_KEY_ENV_VAR: holder.get_private_key(),
        }

    for env_var, key in keys.items():
        monkeypatch.setenv(env_var, base64.b64encode(key).decode('ascii'))

    monkeypatch.setattr(rest_api.application, 'cloud_mode', True)


def cloud_auth_header(rest_api: Any, user_id: int, database: str) -> dict[str, str]:
    """
    Builds the environ override that authenticates a request as a tenant's user

    Args:
        rest_api (Any): The REST test client, whose token generator signs the token
        user_id (int): public_id of the user, stored in the tenant database
        database (str): The tenant database the token names

    Returns:
        dict[str, str]: ``environ_overrides`` for a test-client request
    """
    token: str = rest_api._token_generator.generate_token(  # pylint: disable=protected-access
        payload={'user': {'public_id': user_id, 'database': database}}
    ).decode('UTF-8')

    return {AUTHORIZATION_ENVIRON_KEY: f'Bearer {token}'}
