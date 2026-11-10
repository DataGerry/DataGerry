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
Functional coverage: a user update keeps every key its body leaves out

Measured before: the update validated against the write schema, whose defaults filled every omitted key - a body of
``user_name`` + ``group_id`` re-activated an inactive user, switched an LDAP account to local, reset the API level to 0,
wiped the names, the e-mail and the image, and reset the registration date to now; a body without ``user_name`` was a
400; a sent ``registration_time`` was stored as sent; an edit of the last administrator leaving ``group_id`` out was
refused as a demotion. Now no key is required, an omitted key keeps the stored value, a sent key replaces it, and the
registration date is always the stored one - on PUT and on the PATCH alias alike. The frontend sends the whole user
it read, so its requests behave as before
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
# -------------------------------------------------------------------------------------------------------------------- #

USERS_URL: str = '/users'

KEPT_USER_ID: int = 98771
SELF_EDITOR_ID: int = 98772
LAST_ADMIN_ID: int = 98773
SEEDED_IDS: list[int] = [KEPT_USER_ID, SELF_EDITOR_ID, LAST_ADMIN_ID]

LDAP_AUTHENTICATOR: str = 'LdapAuthenticationProvider'
STORED_API_LEVEL: int = 2
STORED_DIGEST: str = 'stored-digest'
STORED_LIMIT: int = 50
STORED_REGISTRATION: datetime = datetime(2020, 1, 1, tzinfo=timezone.utc)
# The frontend's wire form of a date: {'$date': epoch milliseconds} - 2001-01-01
FORGED_REGISTRATION: dict[str, int] = {'$date': 978307200000}
EDITED_NAME: str = 'Edited'

# The stored values an omitted key must keep - every one differs from the schema default
KEPT_VALUES: dict[str, Any] = {
    CmdbUserKey.USER_NAME.value: 'omitted-keys-user',
    CmdbUserKey.ACTIVE.value: False,
    CmdbUserKey.GROUP_ID.value: ADMIN_GROUP_ID,
    CmdbUserKey.AUTHENTICATOR.value: LDAP_AUTHENTICATOR,
    CmdbUserKey.API_LEVEL.value: STORED_API_LEVEL,
    CmdbUserKey.FIRST_NAME.value: 'Ann',
    CmdbUserKey.LAST_NAME.value: 'Example',
    CmdbUserKey.EMAIL.value: 'ann@example.org',
    CmdbUserKey.IMAGE.value: 'avatar',
}
METHODS: list[str] = ['put', 'patch']


def _user(public_id: int, **values: Any) -> dict[str, Any]:
    """A stored user document carrying every key the model writes"""
    return {
        CmdbUserKey.PUBLIC_ID.value: public_id, CmdbUserKey.USER_NAME.value: f'omitted-keys-{public_id}',
        CmdbUserKey.ACTIVE.value: True, CmdbUserKey.GROUP_ID.value: USER_GROUP_ID,
        CmdbUserKey.PASSWORD.value: STORED_DIGEST, CmdbUserKey.REGISTRATION_TIME.value: STORED_REGISTRATION,
        CmdbUserKey.FIRST_NAME.value: 'First', CmdbUserKey.DATABASE.value: None,
        CmdbUserKey.CONFIG_ITEMS_LIMIT.value: STORED_LIMIT, **values,
    }


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """The inactive LDAP administrator with a full profile, a self-editor and an active administrator"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': {'$in': SEEDED_IDS}})
    users.insert_many([
        _user(KEPT_USER_ID, **KEPT_VALUES),
        _user(SELF_EDITOR_ID),
        _user(LAST_ADMIN_ID, **{CmdbUserKey.GROUP_ID.value: ADMIN_GROUP_ID}),
    ])
    yield users
    users.delete_many({'public_id': {'$in': SEEDED_IDS}})


def _stored(users: Any, public_id: int) -> dict[str, Any]:
    """The user as stored"""
    return users.find_one({'public_id': public_id}, {'_id': 0})


def _send(rest_api, method: str, public_id: int, body: dict[str, Any], **kwargs: Any) -> Any:
    """PUT or PATCH /users/<id>"""
    return getattr(rest_api, method)(f'{USERS_URL}/{public_id}', json=body, **kwargs)


def _accepted(rest_api, method: str, public_id: int, body: dict[str, Any], **kwargs: Any) -> None:
    """The update, asserted accepted"""
    response = _send(rest_api, method, public_id, body, **kwargs)

    assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()


@pytest.mark.parametrize('method', METHODS)
class TestAnOmittedKeyKeepsTheStoredValue:
    """An administrator's update"""

    @pytest.mark.parametrize('key', sorted(KEPT_VALUES))
    def test_each_omitted_key_is_kept(self, rest_api, users, method: str, key: str) -> None:
        """A body that edits another field leaves this one as stored"""
        edited: str = (CmdbUserKey.LAST_NAME.value if key == CmdbUserKey.FIRST_NAME.value
                       else CmdbUserKey.FIRST_NAME.value)

        _accepted(rest_api, method, KEPT_USER_ID, {edited: EDITED_NAME})

        stored = _stored(users, KEPT_USER_ID)
        assert stored[edited] == EDITED_NAME
        assert stored[key] == KEPT_VALUES[key]

    def test_an_empty_body_changes_nothing(self, rest_api, users, method: str) -> None:
        """No key is required any more; the digest and the registration date stay"""
        before = _stored(users, KEPT_USER_ID)

        _accepted(rest_api, method, KEPT_USER_ID, {})

        assert _stored(users, KEPT_USER_ID) == before

    def test_a_sent_key_still_replaces_the_stored_value(self, rest_api, users, method: str) -> None:
        """Including a falsy value and a null profile field"""
        _accepted(rest_api, method, KEPT_USER_ID, {CmdbUserKey.ACTIVE.value: True, CmdbUserKey.API_LEVEL.value: 0,
                                                   CmdbUserKey.EMAIL.value: None})

        stored = _stored(users, KEPT_USER_ID)
        assert (stored['active'], stored['api_level'], stored['email']) == (True, 0, None)
        assert stored['authenticator'] == LDAP_AUTHENTICATOR

    def test_a_sent_registration_time_is_ignored(self, rest_api, users, method: str) -> None:
        """The registration date is the stored one, whatever the body says"""
        _accepted(rest_api, method, KEPT_USER_ID, {CmdbUserKey.REGISTRATION_TIME.value: FORGED_REGISTRATION})

        stored_time: datetime = _stored(users, KEPT_USER_ID)['registration_time']
        assert stored_time.replace(tzinfo=timezone.utc) == STORED_REGISTRATION

    def test_the_password_digest_survives(self, rest_api, users, method: str) -> None:
        """The digest is never taken from the body, nor dropped"""
        _accepted(rest_api, method, KEPT_USER_ID, {CmdbUserKey.FIRST_NAME.value: EDITED_NAME})

        assert _stored(users, KEPT_USER_ID)['password'] == STORED_DIGEST

    def test_a_null_for_a_non_nullable_key_is_still_refused(self, rest_api, users, method: str) -> None:
        """Leaving a key out keeps it; sending null for one that cannot be null is a 400 as before"""
        before = _stored(users, KEPT_USER_ID)

        response = _send(rest_api, method, KEPT_USER_ID, {CmdbUserKey.GROUP_ID.value: None})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(users, KEPT_USER_ID) == before


def _self_editor() -> CmdbUser:
    """The test client's identity for the self-editor (the "user" group: no edit right)"""
    return CmdbUser(public_id=SELF_EDITOR_ID, user_name=f'omitted-keys-{SELF_EDITOR_ID}', active=True,
                    group_id=USER_GROUP_ID)


class TestASelfEdit:
    """A user without the edit right, editing their own record"""

    def test_a_body_with_one_profile_field_passes(self, rest_api, users) -> None:
        """Before: the omitted administrative fields arrived as defaults and the authenticator / group differed"""
        _accepted(rest_api, 'put', SELF_EDITOR_ID, {CmdbUserKey.FIRST_NAME.value: EDITED_NAME}, user=_self_editor())

        stored = _stored(users, SELF_EDITOR_ID)
        assert stored['first_name'] == EDITED_NAME
        assert stored['group_id'] == USER_GROUP_ID

    def test_a_changed_administrative_field_is_still_refused(self, rest_api, users) -> None:
        """Only an omission is no change"""
        response = _send(rest_api, 'put', SELF_EDITOR_ID, {CmdbUserKey.ACTIVE.value: False}, user=_self_editor())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(users, SELF_EDITOR_ID)['active'] is True


class TestTheLastAdministrator:
    """The completion runs before the administrator guards"""

    @pytest.fixture(name='last_administrator')
    def fixture_last_administrator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No other active administrator exists"""
        monkeypatch.setattr(UsersManager, 'has_other_active_member', lambda _self, _group, _user: False)

    @pytest.mark.usefixtures('last_administrator')
    def test_a_profile_edit_leaving_the_group_out_is_no_demotion(self, rest_api, users) -> None:
        """Before: the default group 2 read as a demotion - 400"""
        _accepted(rest_api, 'put', LAST_ADMIN_ID, {CmdbUserKey.FIRST_NAME.value: EDITED_NAME})

        stored = _stored(users, LAST_ADMIN_ID)
        assert (stored['group_id'], stored['first_name']) == (ADMIN_GROUP_ID, EDITED_NAME)

    @pytest.mark.usefixtures('last_administrator')
    def test_a_sent_demotion_is_still_refused(self, rest_api, users) -> None:
        """The rule itself stands"""
        response = _send(rest_api, 'put', LAST_ADMIN_ID, {CmdbUserKey.GROUP_ID.value: USER_GROUP_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(users, LAST_ADMIN_ID)['group_id'] == ADMIN_GROUP_ID
