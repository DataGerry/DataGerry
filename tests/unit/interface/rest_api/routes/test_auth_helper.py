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

Verifies the token is signed and decodable, and that the cloud_mode flag controls whether the user's
database is embedded in the token payload (the only behavioural difference between the two flows).
"""
from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.security.token.validator import TokenValidator
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
