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
Unit tests for generate_token_with_params (auth_helper).

Verifies the token is signed and decodable, that the cloud_mode flag controls whether the user's
database is embedded in the token payload and whose `auth` settings decide the token lifetime (the
tenant's own in cloud mode), and that the issue / expiry times answered are the ones signed into the token.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.security.token.validator import TokenValidator
from cmdb.interface.rest_api.routes import auth_helper
from cmdb.interface.rest_api.routes.auth_helper import generate_token_with_params
# -------------------------------------------------------------------------------------------------------------------- #

TOKEN_USER_ID: int = 99001


def _user(database: str = 'test') -> CmdbUser:
    """Builds a minimal CmdbUser for token generation."""
    return CmdbUser(public_id=TOKEN_USER_ID, user_name='token-user', active=True, database=database)


def _user_claim(database_manager: MongoDatabaseManager, token: bytes) -> dict:
    """Decodes a token and returns its embedded user claim."""
    payload = TokenValidator(database_manager).decode_token(token)
    return payload['DATAGERRY']['value']['user']


def _claims(database_manager: MongoDatabaseManager, token: bytes) -> dict[str, Any]:
    """Decodes a token and returns all of its claims."""
    return TokenValidator(database_manager).decode_token(token)


def test_non_cloud_token_omits_database(database_manager: MongoDatabaseManager) -> None:
    """Without cloud_mode the token carries only the public_id, no database."""
    token, issued, expire = generate_token_with_params(_user(), database_manager)

    assert isinstance(token, bytes)
    assert issued <= expire
    claim = _user_claim(database_manager, token)
    assert claim['public_id'] == TOKEN_USER_ID
    assert 'database' not in claim


def test_cloud_token_includes_database(database_manager: MongoDatabaseManager) -> None:
    """With cloud_mode the token embeds the user's database."""
    token, _issued, _expire = generate_token_with_params(
        _user(database='cloud_db_x'), database_manager, cloud_mode=True,
    )

    claim = _user_claim(database_manager, token)
    assert claim['public_id'] == TOKEN_USER_ID
    assert claim['database'] == 'cloud_db_x'


def test_the_times_answered_are_the_tokens_own(database_manager: MongoDatabaseManager) -> None:
    """token_expire - what the frontend's session timer runs on - is the token's exp, not a second clock read"""
    token, issued, expire = generate_token_with_params(_user(), database_manager)

    claims: dict[str, Any] = _claims(database_manager, token)
    assert claims['iat'] == issued
    assert claims['exp'] == expire


@pytest.mark.parametrize('cloud_mode, expected_database', [(True, 'cloud_db_x'), (False, None)],
                         ids=['cloud', 'on-premise'])
def test_the_lifetime_is_read_for_the_users_database(
        database_manager: MongoDatabaseManager, monkeypatch: pytest.MonkeyPatch,
        cloud_mode: bool, expected_database: str | None) -> None:
    """In cloud mode the tenant's auth settings decide the lifetime; on premise the one database's do"""
    bound_to: list[str | None] = []
    real_generator = auth_helper.TokenGenerator

    def _recording(dbm: MongoDatabaseManager, database: str | None = None) -> Any:
        bound_to.append(database)
        return real_generator(dbm, database)

    monkeypatch.setattr(auth_helper, 'TokenGenerator', _recording)

    generate_token_with_params(_user(database='cloud_db_x'), database_manager, cloud_mode=cloud_mode)

    assert bound_to == [expected_database]
