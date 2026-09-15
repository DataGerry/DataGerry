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
Unit tests for cmdb.models.cached_user_model.cmdb_cached_user

DB-free: the class is exercised directly. Covers __init__ (incl. the creation_time default and the
error wrap), from_data (datetime / string / missing-key), to_json (round-trip and the type guard) and
the declared indexes - the unique email index, the creation_time TTL, and the unique public_id index
inherited from CmdbDAO, which is what makes an entry written without a public_id a duplicate-key risk
"""
from typing import Any
from datetime import datetime, timedelta, timezone

import pytest

from cmdb.models.cached_user_model import CACHE_TTL_SECONDS, CachedUserKey, CmdbCachedUser
from cmdb.errors.models.cmdb_cached_user import (
    CmdbCachedUserInitError,
    CmdbCachedUserInitFromDataError,
    CmdbCachedUserToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 7
USER_NAME: str = 'acme_user'
PASSWORD: str = 'hmac-of-the-password'
EMAIL: str = 'user@acme.com'
SUBSCRIPTIONS: list[dict[str, Any]] = [{'database': 'db_acme', 'api_level': 1, 'config_item_limit': 10}]
CREATION_TIME: datetime = datetime(2026, 8, 25, 10, 30, tzinfo=timezone.utc)
CREATION_TIME_STRING: str = '2026-08-25T10:30:00+00:00'


def _document(**overrides: Any) -> dict[str, Any]:
    """Builds a complete cached-user document; overrides replace or remove (via None key) entries."""
    document: dict[str, Any] = {
        CachedUserKey.PUBLIC_ID.value: PUBLIC_ID,
        CachedUserKey.USER_NAME.value: USER_NAME,
        CachedUserKey.PASSWORD.value: PASSWORD,
        CachedUserKey.EMAIL.value: EMAIL,
        CachedUserKey.ACTIVE.value: True,
        CachedUserKey.SUBSCRIPTIONS.value: SUBSCRIPTIONS,
        CachedUserKey.CREATION_TIME.value: CREATION_TIME,
    }
    document.update(overrides)

    return document


def _cached_user(**overrides: Any) -> CmdbCachedUser:
    """Builds a CmdbCachedUser from the default document."""
    return CmdbCachedUser.from_data(_document(**overrides))


class TestInit:
    """CmdbCachedUser.__init__ stores the cached user's values."""

    def test_stores_every_value(self) -> None:
        """Each constructor argument becomes an attribute."""
        cached_user = CmdbCachedUser(
            public_id=PUBLIC_ID,
            user_name=USER_NAME,
            password=PASSWORD,
            email=EMAIL,
            active=True,
            subscriptions=SUBSCRIPTIONS,
            creation_time=CREATION_TIME,
        )

        assert cached_user.public_id == PUBLIC_ID
        assert cached_user.user_name == USER_NAME
        assert cached_user.password == PASSWORD
        assert cached_user.email == EMAIL
        assert cached_user.active is True
        assert cached_user.subscriptions == SUBSCRIPTIONS
        assert cached_user.creation_time == CREATION_TIME

    def test_missing_creation_time_defaults_to_now(self) -> None:
        """A None creation_time starts the TTL at 'now', as an aware UTC datetime."""
        before = datetime.now(timezone.utc)

        cached_user = CmdbCachedUser(
            public_id=PUBLIC_ID,
            user_name=USER_NAME,
            password=PASSWORD,
            email=EMAIL,
            active=True,
            subscriptions=SUBSCRIPTIONS,
            creation_time=None,
        )

        assert cached_user.creation_time.tzinfo is not None
        assert before <= cached_user.creation_time <= datetime.now(timezone.utc) + timedelta(seconds=1)

    def test_invalid_public_id_raises_init_error(self) -> None:
        """A public_id that is not a number is reported as a CmdbCachedUserInitError."""
        with pytest.raises(CmdbCachedUserInitError):
            CmdbCachedUser(
                public_id='not-a-number',
                user_name=USER_NAME,
                password=PASSWORD,
                email=EMAIL,
                active=True,
                subscriptions=SUBSCRIPTIONS,
                creation_time=CREATION_TIME,
            )


class TestFromData:
    """CmdbCachedUser.from_data builds an instance from a stored document."""

    def test_builds_from_a_complete_document(self) -> None:
        """Every key is read into the instance."""
        cached_user = _cached_user()

        assert cached_user.public_id == PUBLIC_ID
        assert cached_user.email == EMAIL
        assert cached_user.subscriptions == SUBSCRIPTIONS
        assert cached_user.creation_time == CREATION_TIME

    def test_string_creation_time_is_parsed(self) -> None:
        """A creation_time stored as a string is turned into a datetime."""
        cached_user = _cached_user(creation_time=CREATION_TIME_STRING)

        assert cached_user.creation_time == CREATION_TIME

    def test_none_creation_time_falls_back_to_now(self) -> None:
        """A document without a creation_time value gets 'now' rather than None."""
        cached_user = _cached_user(creation_time=None)

        assert isinstance(cached_user.creation_time, datetime)

    @pytest.mark.parametrize('missing_key', [key.value for key in CachedUserKey])
    def test_missing_key_raises_from_data_error(self, missing_key: str) -> None:
        """
        Every key is mandatory

        Note the consequence for 'active': no write path stores it, so from_data raises on a document
        the live cache actually holds. That mismatch is a filed decision, not something these tests
        paper over
        """
        document = _document()
        del document[missing_key]

        with pytest.raises(CmdbCachedUserInitFromDataError):
            CmdbCachedUser.from_data(document)


class TestToJson:
    """CmdbCachedUser.to_json converts an instance back into a document."""

    def test_round_trips_a_document(self) -> None:
        """from_data followed by to_json returns the original document."""
        assert CmdbCachedUser.to_json(_cached_user()) == _document()

    def test_creation_time_stays_a_datetime(self) -> None:
        """The TTL index needs a real date, so creation_time is not stringified."""
        assert isinstance(CmdbCachedUser.to_json(_cached_user())[CachedUserKey.CREATION_TIME.value], datetime)

    def test_wrong_type_raises_to_json_error(self) -> None:
        """Anything that is not a CmdbCachedUser is refused."""
        with pytest.raises(CmdbCachedUserToJsonError):
            CmdbCachedUser.to_json({'public_id': PUBLIC_ID})


class TestIndexes:
    """The declared indexes are what keeps the cache consistent."""

    def test_email_index_is_unique(self) -> None:
        """One cache entry per email."""
        indexes = {index.document['name']: index.document for index in CmdbCachedUser.get_index_keys()}

        assert indexes[CachedUserKey.EMAIL.value]['unique'] is True

    def test_creation_time_index_expires_after_the_cache_ttl(self) -> None:
        """MongoDB removes an entry CACHE_TTL_SECONDS after it was written."""
        indexes = {index.document['name']: index.document for index in CmdbCachedUser.get_index_keys()}

        assert indexes[CachedUserKey.CREATION_TIME.value]['expireAfterSeconds'] == CACHE_TTL_SECONDS

    def test_public_id_index_is_inherited_and_unique(self) -> None:
        """
        The unique public_id index of CmdbDAO applies here too

        It is why a write that stores no public_id is a duplicate-key risk: a unique index treats every
        missing value as the same null
        """
        indexes = {index.document['name']: index.document for index in CmdbCachedUser.get_index_keys()}

        assert indexes[CachedUserKey.PUBLIC_ID.value]['unique'] is True
