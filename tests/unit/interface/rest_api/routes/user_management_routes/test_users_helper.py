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

Pure tests of the extracted route helpers: ``complete_user_update`` (an omitted key keeps the stored value, the
password excepted), ``prepare_cloud_user``
(the cloud-mode-only create preparation - non-cloud no-op, email presence + uniqueness guards, the
manager-get error mapping, and the local users-file mirror), and the update's field guard -
``guard_user_update`` over every field class, for a self-edit and for a holder of the edit right (the right
itself is ``route_utils.user_has_right``, tested with it). No app or DB is booted; the manager and request user
are lightweight stubs and the local users file is patched with mock_open.
"""
from typing import Any
from unittest.mock import mock_open, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.user_management_routes import users_helper
from cmdb.interface.rest_api.routes.user_management_routes.users_helper import (
    complete_user_update,
    guard_user_update,
    prepare_cloud_user,
)
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    ADMINISTRATIVE_FIELDS,
    PROFILE_FIELDS,
    ROUTE_HANDLED_FIELDS,
    SERVER_OWNED_FIELDS,
)
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.errors.manager.users_manager import UsersManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

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
#                                               guard_user_update                                                      #
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

    def test_a_key_the_body_leaves_out_is_no_change(self) -> None:
        """Only a sent value is judged; the guard adds nothing but the digest (the route completed the body)"""
        data: dict[str, Any] = {CmdbUserKey.USER_NAME.value: 'alice'}

        guard_user_update(_stored_user(), data, may_administer=False)

        assert data == {CmdbUserKey.USER_NAME.value: 'alice', CmdbUserKey.PASSWORD.value: STORED_DIGEST}

    @pytest.mark.parametrize('field', sorted(PROFILE_FIELDS))
    def test_a_self_edit_may_change_a_profile_field(self, field: CmdbUserKey) -> None:
        """Names, email and image are the user's own"""
        data = {**_as_sent_back(), field.value: 'changed'}

        guard_user_update(_stored_user(), data, may_administer=False)

        assert data[field.value] == 'changed'


# -------------------------------------------------------------------------------------------------------------------- #
#                                              complete_user_update                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCompleteUserUpdate:
    """The update body completed from the stored user, before any guard reads it"""

    def test_every_omitted_key_takes_the_stored_value(self) -> None:
        """An empty body is the stored user - the digest excepted"""
        stored_user: CmdbUser = _stored_user()
        stored: dict[str, Any] = CmdbUser.to_json(stored_user)

        completed = complete_user_update({}, stored_user)

        assert completed == {key: value for key, value in stored.items() if key != CmdbUserKey.PASSWORD.value}

    def test_a_sent_key_wins(self) -> None:
        """Including a falsy value: False is a value, not an omission"""
        sent: dict[str, Any] = {CmdbUserKey.ACTIVE.value: False, CmdbUserKey.FIRST_NAME.value: None}

        completed = complete_user_update(sent, _stored_user())

        assert completed[CmdbUserKey.ACTIVE.value] is False
        assert completed[CmdbUserKey.FIRST_NAME.value] is None
        assert completed[CmdbUserKey.GROUP_ID.value] == STORED_GROUP_ID

    def test_the_password_is_never_taken_from_the_stored_user(self) -> None:
        """The guard refuses a body carrying one - a filled-in digest would read as one"""
        assert CmdbUserKey.PASSWORD.value not in complete_user_update({}, _stored_user())

    def test_the_body_is_not_mutated(self) -> None:
        """A new dict"""
        sent: dict[str, Any] = {CmdbUserKey.FIRST_NAME.value: 'Alicia'}

        complete_user_update(sent, _stored_user())

        assert sent == {CmdbUserKey.FIRST_NAME.value: 'Alicia'}

    def test_a_completed_body_with_no_change_passes_every_guarded_field(self) -> None:
        """The completion and the guard together: a self-edit sending one profile field passes"""
        data = complete_user_update({CmdbUserKey.FIRST_NAME.value: 'Alicia'}, _stored_user())

        guard_user_update(_stored_user(), data, may_administer=False)

        assert data[CmdbUserKey.FIRST_NAME.value] == 'Alicia'
        assert data[CmdbUserKey.PASSWORD.value] == STORED_DIGEST

