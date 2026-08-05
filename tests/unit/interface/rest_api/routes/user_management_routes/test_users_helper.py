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
Unit tests for cmdb.interface.rest_api.routes.user_management_routes.users_helper

Pure tests of the two extracted route helpers: ``parse_registration_time`` / ``apply_registration_time``
(BSON ``$date`` and ISO-string coercion, passthrough of unrecognised shapes) and ``prepare_cloud_user``
(the cloud-mode-only create preparation - non-cloud no-op, email presence + uniqueness guards, the
manager-get error mapping, and the local users-file mirror). No app or DB is booted; the manager and
request user are lightweight stubs and the local users file is patched with mock_open.
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import mock_open, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.user_management_routes import users_helper
from cmdb.interface.rest_api.routes.user_management_routes.users_helper import (
    apply_registration_time,
    parse_registration_time,
    prepare_cloud_user,
)
from cmdb.errors.manager.users_manager import UsersManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ISO_STRING: str = '2024-01-02T03:04:05Z'
EPOCH_MS: int = 1_704_164_645_000  # 2024-01-02T03:04:05Z in milliseconds
USER_EMAIL: str = 'new@example.com'
TARGET_DATABASE: str = 'tenant-db'


class _StubUser:
    """Minimal request-user stub exposing only the database attribute the helper reads."""

    def __init__(self, database: str = TARGET_DATABASE) -> None:
        self.database = database


class _KeyErrorUser:
    """Request-user stub whose database access raises KeyError, exercising the defensive guard."""

    @property
    def database(self) -> str:
        """Raises KeyError to simulate an unresolvable database on the request user."""
        raise KeyError('database')


class _StubUsersManager:
    """Stand-in for UsersManager recording the email lookup and returning a canned result."""

    def __init__(self, existing: Any = None, raises: Exception | None = None) -> None:
        self._existing = existing
        self._raises = raises
        self.queried_with: dict[str, Any] | None = None

    def get_user_by(self, query: dict[str, Any]) -> Any:
        """Mirrors UsersManager.get_user_by against the canned result / exception."""
        self.queried_with = query

        if self._raises is not None:
            raise self._raises

        return self._existing


def _base_payload() -> dict[str, Any]:
    """A create payload carrying the fields the cloud preparation reads."""
    return {'user_name': 'new-user', 'email': USER_EMAIL}


class TestParseRegistrationTime:
    """parse_registration_time coerces the recognised shapes and passes everything else through."""

    def test_bson_date_iso_string(self) -> None:
        """A ``{'$date': <iso string>}`` wrapper is parsed into a datetime."""
        result = parse_registration_time({'$date': ISO_STRING})

        assert isinstance(result, datetime)
        assert result == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def test_bson_date_epoch_millis(self) -> None:
        """A ``{'$date': <epoch ms int>}`` wrapper is parsed into a UTC datetime."""
        result = parse_registration_time({'$date': EPOCH_MS})

        assert isinstance(result, datetime)
        assert result == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def test_plain_iso_string(self) -> None:
        """A bare ISO string is parsed into a datetime."""
        result = parse_registration_time(ISO_STRING)

        assert result == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def test_dict_without_date_key_is_unchanged(self) -> None:
        """A dict without a ``$date`` key is returned unchanged."""
        raw = {'not_date': 1}

        assert parse_registration_time(raw) is raw

    def test_bson_date_unexpected_type_is_unchanged(self) -> None:
        """A ``$date`` value that is neither str nor int is returned as the original dict."""
        raw = {'$date': 3.5}

        assert parse_registration_time(raw) is raw

    def test_none_is_unchanged(self) -> None:
        """None is returned unchanged."""
        assert parse_registration_time(None) is None


class TestApplyRegistrationTime:
    """apply_registration_time normalises the key in place, only when present."""

    def test_normalises_when_present(self) -> None:
        """A present registration_time is replaced with its parsed datetime."""
        data = {'registration_time': ISO_STRING}

        apply_registration_time(data)

        assert data['registration_time'] == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def test_absent_key_stays_absent(self) -> None:
        """When registration_time is absent the key is not added."""
        data: dict[str, Any] = {'user_name': 'x'}

        apply_registration_time(data)

        assert 'registration_time' not in data


class TestPrepareCloudUser:
    """prepare_cloud_user is a no-op outside cloud mode and enforces the cloud create rules within it."""

    def test_non_cloud_is_noop(self) -> None:
        """Outside cloud mode nothing is mutated and the manager is never queried."""
        data = _base_payload()
        manager = _StubUsersManager()

        prepare_cloud_user(data, 'pw', _StubUser(), manager, cloud_mode=False, local_mode=False)

        assert 'database' not in data
        assert manager.queried_with is None

    def test_binds_database_and_checks_unique_email(self) -> None:
        """In cloud mode the target database is bound and the email is checked for uniqueness."""
        data = _base_payload()
        manager = _StubUsersManager(existing=None)

        prepare_cloud_user(data, 'pw', _StubUser(), manager, cloud_mode=True, local_mode=False)

        assert data['database'] == TARGET_DATABASE
        assert manager.queried_with == {'email': USER_EMAIL}

    def test_unresolvable_database_aborts_400(self) -> None:
        """A request user whose database cannot be resolved aborts the create with 400."""
        with pytest.raises(HTTPException) as exc:
            prepare_cloud_user(
                _base_payload(), 'pw', _KeyErrorUser(), _StubUsersManager(), cloud_mode=True, local_mode=False
            )

        assert exc.value.code == 400

    def test_missing_email_aborts_400(self) -> None:
        """A cloud create without an email aborts with 400."""
        data = {'user_name': 'new-user'}  # no email

        with pytest.raises(HTTPException) as exc:
            prepare_cloud_user(data, 'pw', _StubUser(), _StubUsersManager(), cloud_mode=True, local_mode=False)

        assert exc.value.code == 400

    def test_duplicate_email_aborts_400(self) -> None:
        """A cloud create whose email is already in use aborts with 400."""
        manager = _StubUsersManager(existing={'public_id': 5})

        with pytest.raises(HTTPException) as exc:
            prepare_cloud_user(_base_payload(), 'pw', _StubUser(), manager, cloud_mode=True, local_mode=False)

        assert exc.value.code == 400

    def test_manager_get_error_aborts_400(self) -> None:
        """A UsersManagerGetError during the email lookup is mapped to 400."""
        manager = _StubUsersManager(raises=UsersManagerGetError('boom'))

        with pytest.raises(HTTPException) as exc:
            prepare_cloud_user(_base_payload(), 'pw', _StubUser(), manager, cloud_mode=True, local_mode=False)

        assert exc.value.code == 400

    def test_local_mode_writes_new_user_to_file(self) -> None:
        """In local cloud mode a new email is mirrored into the users file."""
        data = _base_payload()
        opener = mock_open(read_data='{}')

        with patch.object(users_helper, 'open', opener, create=True):
            prepare_cloud_user(data, 'plain-pw', _StubUser(), _StubUsersManager(), cloud_mode=True, local_mode=True)

        # the file was reopened for writing and json.dump wrote at least once
        opener.assert_any_call(users_helper.TEST_USERS_FILE, 'w', encoding='utf-8')
        handle = opener()
        assert handle.write.called

    def test_local_mode_existing_email_in_file_aborts_400(self) -> None:
        """In local cloud mode an email already present in the users file aborts with 400."""
        opener = mock_open(read_data=f'{{"{USER_EMAIL}": {{}}}}')

        with patch.object(users_helper, 'open', opener, create=True):
            with pytest.raises(HTTPException) as exc:
                prepare_cloud_user(
                    _base_payload(), 'pw', _StubUser(), _StubUsersManager(), cloud_mode=True, local_mode=True
                )

        assert exc.value.code == 400
