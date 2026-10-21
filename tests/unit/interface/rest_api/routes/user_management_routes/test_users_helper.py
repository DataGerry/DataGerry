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

Pure tests of the extracted route helpers: ``parse_registration_time`` / ``apply_registration_time``
(BSON ``$date`` and ISO-string coercion, passthrough of unrecognised shapes), ``prepare_cloud_user``
(the cloud-mode-only create preparation - non-cloud no-op, email presence + uniqueness guards, the
manager-get error mapping, and the local users-file mirror), and the update's field guard -
``holds_right`` and ``guard_user_update`` over every field class, for a self-edit and for a holder of
the edit right. No app or DB is booted; the manager and request user are lightweight stubs and the
local users file is patched with mock_open.
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, mock_open, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.user_management_routes import users_helper
from cmdb.interface.rest_api.routes.user_management_routes.users_helper import (
    apply_registration_time,
    guard_user_update,
    holds_right,
    parse_registration_time,
    prepare_cloud_user,
)
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    ADMINISTRATIVE_FIELDS,
    PROFILE_FIELDS,
    ROUTE_HANDLED_FIELDS,
    SERVER_OWNED_FIELDS,
    UserAccessRight,
)
from cmdb.models.user_model import CmdbUser, CmdbUserKey
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

    def test_bson_date_float_millis_is_parsed(self) -> None:
        """
        A ``$date`` carrying a float is read as milliseconds like an int is.

        It goes through the shared ``coerce_mongo_datetime``, which reads every shape the API
        round-trip produces - a JSON client is free to send the millis as a float.
        """
        result = parse_registration_time({'$date': float(EPOCH_MS)})

        assert result == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def test_bson_date_boolean_is_unchanged(self) -> None:
        """
        A ``$date`` that cannot be a timestamp is passed through untouched.

        bool is an int subclass in Python, so before the shared caster's guard this read as one
        millisecond past the epoch instead of being refused.
        """
        raw = {'$date': True}

        assert parse_registration_time(raw) is raw

    def test_bson_date_unreadable_string_is_unchanged(self) -> None:
        """An unparseable payload leaves the value as it was, for the caller to reject."""
        raw = {'$date': 'not-a-timestamp'}

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


# -------------------------------------------------------------------------------------------------------------------- #
#                                         holds_right + guard_user_update                                             #
# -------------------------------------------------------------------------------------------------------------------- #
STORED_DIGEST: str = 'stored-digest'
STORED_DATABASE: str = 'tenant-a'
STORED_LIMIT: int = 50
STORED_GROUP_ID: int = 2
OTHER_GROUP_ID: int = 1

# A value different from the stored one, per guarded field - what an attacker would send
CHANGED_VALUES: dict[CmdbUserKey, Any] = {
    CmdbUserKey.GROUP_ID: OTHER_GROUP_ID,
    CmdbUserKey.ACTIVE: False,
    CmdbUserKey.AUTHENTICATOR: 'LdapAuthenticationProvider',
    CmdbUserKey.API_LEVEL: 3,
    CmdbUserKey.USER_NAME: 'someone-else',
    CmdbUserKey.DATABASE: 'tenant-b',
    CmdbUserKey.CONFIG_ITEMS_LIMIT: 999_999,
}


def _stored_user() -> CmdbUser:
    """The user as stored: a local account in the default group of one tenant."""
    return CmdbUser(public_id=7, user_name='alice', active=True, group_id=STORED_GROUP_ID,
                    database=STORED_DATABASE, config_items_limit=STORED_LIMIT, password=STORED_DIGEST,
                    email='alice@example.com')


def _as_sent_back() -> dict[str, Any]:
    """What a client sends after reading the user: the public document, without the digest."""
    document: dict[str, Any] = CmdbUser.to_public_json(_stored_user())
    document.pop(CmdbUserKey.PUBLIC_ID.value)
    document.pop(CmdbUserKey.REGISTRATION_TIME.value)

    return document


def _refusal(data: dict[str, Any], may_administer: bool) -> HTTPException:
    """Runs the guard expecting a refusal and answers it."""
    with pytest.raises(HTTPException) as refused:
        guard_user_update(_stored_user(), data, may_administer=may_administer)

    return refused.value


class TestHoldsRight:
    """The right check the update route uses to tell a self-edit from an administrator"""

    def test_a_missing_group_holds_nothing(self) -> None:
        """No group, no right - never a pass by default"""
        groups_manager = MagicMock()
        groups_manager.get_group.return_value = None

        assert holds_right(_stored_user(), UserAccessRight.EDIT.value, groups_manager) is False

    @pytest.mark.parametrize('direct, extended, expected', [
        (True, False, True),
        (False, True, True),
        (False, False, False),
    ])
    def test_a_direct_or_an_extended_right_counts(self, direct: bool, extended: bool, expected: bool) -> None:
        """The same two checks protect runs: the right itself, or a broader right covering it"""
        groups_manager = MagicMock()
        groups_manager.get_group.return_value.has_right.return_value = direct
        groups_manager.get_group.return_value.has_extended_right.return_value = extended

        assert holds_right(_stored_user(), UserAccessRight.EDIT.value, groups_manager) is expected
        groups_manager.get_group.assert_called_once_with(STORED_GROUP_ID)


class TestFieldClasses:
    """Every user field is placed in exactly one class, so a new field cannot slip through unguarded"""

    CLASSES: tuple[frozenset[CmdbUserKey], ...] = (
        PROFILE_FIELDS, ADMINISTRATIVE_FIELDS, SERVER_OWNED_FIELDS, ROUTE_HANDLED_FIELDS,
    )

    def test_the_classes_cover_every_user_key(self) -> None:
        """A CmdbUserKey in none of the classes fails here"""
        assert frozenset().union(*self.CLASSES) == frozenset(CmdbUserKey)

    def test_no_field_is_in_two_classes(self) -> None:
        """The classes are disjoint - a field has one rule, not two"""
        assert sum(len(fields) for fields in self.CLASSES) == len(CmdbUserKey)

    def test_every_guarded_field_has_a_changed_value_under_test(self) -> None:
        """The refusal tests below cover every compared field, not a sample"""
        assert set(CHANGED_VALUES) == (ADMINISTRATIVE_FIELDS | SERVER_OWNED_FIELDS) - {CmdbUserKey.PASSWORD}


class TestGuardUserUpdate:
    """Which fields a self-edit and an administrator may change on PUT /users/<id>"""

    @pytest.mark.parametrize('may_administer', [False, True])
    def test_the_user_sent_back_unchanged_passes(self, may_administer: bool) -> None:
        """What both frontend screens send - the read document, edited profile fields only - is accepted"""
        data = _as_sent_back()
        data[CmdbUserKey.FIRST_NAME.value] = 'Alicia'

        guard_user_update(_stored_user(), data, may_administer=may_administer)

        assert data[CmdbUserKey.FIRST_NAME.value] == 'Alicia'

    @pytest.mark.parametrize('field', sorted(ADMINISTRATIVE_FIELDS))
    def test_a_self_edit_may_not_change_an_administrative_field(self, field: CmdbUserKey) -> None:
        """group_id, active, authenticator, api_level and user_name need the edit right"""
        data = {**_as_sent_back(), field.value: CHANGED_VALUES[field]}

        refused = _refusal(data, may_administer=False)

        assert refused.code == 400
        assert field.value in refused.description

    @pytest.mark.parametrize('field', sorted(ADMINISTRATIVE_FIELDS))
    def test_an_administrator_may_change_an_administrative_field(self, field: CmdbUserKey) -> None:
        """Holding the edit right lifts exactly this class"""
        data = {**_as_sent_back(), field.value: CHANGED_VALUES[field]}

        guard_user_update(_stored_user(), data, may_administer=True)

        assert data[field.value] == CHANGED_VALUES[field]

    @pytest.mark.parametrize('may_administer', [False, True])
    @pytest.mark.parametrize('field', [CmdbUserKey.DATABASE, CmdbUserKey.CONFIG_ITEMS_LIMIT])
    def test_nobody_changes_a_server_owned_field(self, field: CmdbUserKey, may_administer: bool) -> None:
        """The tenant database and the ConfigItem limit are refused for an administrator too"""
        data = {**_as_sent_back(), field.value: CHANGED_VALUES[field]}

        refused = _refusal(data, may_administer=may_administer)

        assert refused.code == 400
        assert field.value in refused.description

    @pytest.mark.parametrize('may_administer', [False, True])
    def test_a_password_in_the_body_is_refused(self, may_administer: bool) -> None:
        """A password changes through its own route, which hashes it - never raw through this one"""
        data = {**_as_sent_back(), CmdbUserKey.PASSWORD.value: 'plaintext'}

        assert _refusal(data, may_administer=may_administer).code == 400

    @pytest.mark.parametrize('sent', [{}, {CmdbUserKey.PASSWORD.value: None}])
    def test_the_stored_digest_is_kept(self, sent: dict[str, Any]) -> None:
        """No password, or a null one, keeps the stored digest rather than wiping it"""
        data = {**_as_sent_back(), **sent}

        guard_user_update(_stored_user(), data, may_administer=True)

        assert data[CmdbUserKey.PASSWORD.value] == STORED_DIGEST

    def test_a_self_edit_that_leaves_fields_out_keeps_the_stored_values(self) -> None:
        """An absent guarded key is copied from the stored user, so it is not reset to its default"""
        data: dict[str, Any] = {CmdbUserKey.USER_NAME.value: 'alice', CmdbUserKey.ACTIVE.value: True}

        guard_user_update(_stored_user(), data, may_administer=False)

        assert data[CmdbUserKey.GROUP_ID.value] == STORED_GROUP_ID
        assert data[CmdbUserKey.DATABASE.value] == STORED_DATABASE
        assert data[CmdbUserKey.CONFIG_ITEMS_LIMIT.value] == STORED_LIMIT
        assert data[CmdbUserKey.PASSWORD.value] == STORED_DIGEST

    @pytest.mark.parametrize('field', sorted(PROFILE_FIELDS))
    def test_a_self_edit_may_change_a_profile_field(self, field: CmdbUserKey) -> None:
        """Names, email and image are the user's own"""
        data = {**_as_sent_back(), field.value: 'changed'}

        guard_user_update(_stored_user(), data, may_administer=False)

        assert data[field.value] == 'changed'
