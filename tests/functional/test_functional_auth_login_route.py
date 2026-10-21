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
Functional tests for the ``/auth`` routes.

Validates the login WORKFLOW: the non-cloud (AuthModule) flow end-to-end with the
seeded admin/admin, the cloud (ServicePortal) flow's subscription matrix and error mapping (helpers
monkeypatched), the settings/providers reads, and update_auth_settings (incl. a bad
payload -> 400 not 500). Cloud tests flip the app into cloud+local mode so token signing uses the dev
keys instead of the (unset) cloud env keys.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.auth_module import AuthModule
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.errors.security.security_errors import (
    InvalidCloudUserError,
    NoAccessTokenError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.errors.database import DatabaseConnectionError
from cmdb.errors.manager.users_manager import UsersManagerGetError, UsersManagerInsertError
from cmdb.errors.models.cmdb_auth_settings import AuthSettingsInitError
from cmdb.interface.rest_api.routes import auth_helper, auth_routes
from cmdb.interface.rest_api.routes.auth_constants import LoginKey
from cmdb.interface.blueprints.api_blueprint_constants import BODY_NOT_AN_OBJECT_MESSAGE
from cmdb.security.auth.auth_settings_masking import MASKED_SECRET
from cmdb.security.auth.base_provider_config import PROVIDER_ACTIVE_KEY
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID as AUTH_SETTINGS_SECTION
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
SETTINGS_URL: str = '/auth/settings'
PROVIDERS_URL: str = '/auth/providers'
LDAP_PROVIDER: str = 'LdapAuthenticationProvider'
LOCAL_PROVIDER: str = 'LocalAuthenticationProvider'

CLOUD_USER_ID: int = 99101


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _enable_cloud(rest_api, monkeypatch, *, local: bool = True) -> None:
    """Flips the app into cloud (+ optionally local) mode for the duration of a test."""
    monkeypatch.setattr(rest_api.application, 'cloud_mode', True)
    monkeypatch.setattr(rest_api.application, 'local_mode', local)


def _cloud_user() -> CmdbUser:
    """A CmdbUser as retrieve_user would return it in the cloud flow."""
    return CmdbUser(public_id=CLOUD_USER_ID, user_name='cloud-user', active=True, database='cloud_db')


def _single_subscription_portal(_user_name, _password):
    """ServicePortal stub returning exactly one subscription."""
    return {'subscriptions': [{'id': 's1', 'name': 'Sub 1', 'database': 'db1'}]}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              NON-CLOUD (LOCAL) LOGIN                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLocalLogin:
    """POST /auth/login in the default (non-cloud) mode via the AuthModule flow."""

    def test_login_success_returns_token(self, rest_api) -> None:
        """The seeded admin/admin logs in and receives a token (end-to-end workflow check)."""
        response = rest_api.post(LOGIN_URL, json={'user_name': 'admin', 'password': 'admin'})

        assert response.status_code == HTTPStatus.OK
        assert 'token' in response.get_json()

    def test_login_wrong_password_returns_401(self, rest_api) -> None:
        """A wrong password is rejected with 401 (provider AuthenticationError -> 401)."""
        response = rest_api.post(LOGIN_URL, json={'user_name': 'admin', 'password': 'wrong'})

        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_login_no_body_returns_400(self, rest_api) -> None:
        """An empty body is rejected with 400."""
        assert rest_api.post(LOGIN_URL, json={}).status_code == HTTPStatus.BAD_REQUEST

    def test_login_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error in the local flow maps to 500."""
        monkeypatch.setattr(AuthModule, 'login', _raiser(RuntimeError('boom')))

        assert rest_api.post(LOGIN_URL, json={'user_name': 'admin', 'password': 'admin'}).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_login_no_user_returned_returns_401(self, rest_api, monkeypatch) -> None:
        """When the provider returns no user, the flow responds 401 (the abort propagates)."""
        monkeypatch.setattr(AuthModule, 'login', lambda *_a, **_k: None)

        assert rest_api.post(LOGIN_URL, json={'user_name': 'admin', 'password': 'admin'}).status_code \
            == HTTPStatus.UNAUTHORIZED



# -------------------------------------------------------------------------------------------------------------------- #
#                                                LOGIN BODY CONTRACT                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheLoginBodyContract:
    """A body that breaks the contract is a 400 naming the field - before any credential is checked."""

    @pytest.mark.parametrize(('body', 'named'), [
        ({'user_name': 'admin'}, LoginKey.PASSWORD.value),
        ({'password': 'admin'}, LoginKey.USER_NAME.value),
        ({'user_name': None, 'password': 'admin'}, LoginKey.USER_NAME.value),
        ({'user_name': 5, 'password': 'admin'}, LoginKey.USER_NAME.value),
        ({'user_name': 'admin', 'password': 5}, LoginKey.PASSWORD.value),
        ({'user_name': '', 'password': 'admin'}, LoginKey.USER_NAME.value),
        ({'user_name': 'admin', 'password': ''}, LoginKey.PASSWORD.value),
        ({'user_name': 'admin', 'password': 'admin', 'subscription': 's1'}, LoginKey.SUBSCRIPTION.value),
        ({'user_name': 'admin', 'password': 'admin', 'subscription': {'name': 'Sub'}}, LoginKey.SUBSCRIPTION.value),
    ], ids=['no password', 'no user_name', 'null user_name', 'numeric user_name', 'numeric password',
            'empty user_name', 'empty password', 'subscription string', 'subscription without id'])
    def test_a_malformed_field_is_named(self, rest_api, body: dict[str, Any], named: str) -> None:
        """400, and the message names the field"""
        response = rest_api.post(LOGIN_URL, json=body, unauthorized=True)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert named in response.get_json()['message']

    @pytest.mark.parametrize('raw_body', ['["admin"]', '"admin"', '5', 'null'], ids=['list', 'string', 'number', 'null'])
    def test_a_body_that_is_not_an_object_is_refused(self, rest_api, raw_body: str) -> None:
        """Its own message, not a validator failure and never a 500"""
        response = rest_api.post(LOGIN_URL, data=raw_body, content_type='application/json', unauthorized=True)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == f'{BODY_NOT_AN_OBJECT_MESSAGE}!'

    @pytest.mark.parametrize('user_name', [{'$ne': 'nobody'}, {'$regex': '^adm'}, ['admin']],
                             ids=['$ne', '$regex', 'list'])
    def test_a_query_shaped_login_name_never_reaches_the_lookup(self, rest_api, monkeypatch, user_name: Any) -> None:
        """Refused by the contract, with the right password - the AuthModule is never asked"""
        calls: list[Any] = []
        monkeypatch.setattr(AuthModule, 'login', lambda _self, name, _password: calls.append(name))

        response = rest_api.post(LOGIN_URL, json={'user_name': user_name, 'password': 'admin'}, unauthorized=True)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert not calls

    def test_the_frontends_first_step_is_accepted(self, rest_api) -> None:
        """The control: user_name + password"""
        assert rest_api.post(LOGIN_URL, json={'user_name': 'admin', 'password': 'admin'}).status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                                CLOUD LOGIN FLOW                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCloudLogin:
    """POST /auth/login in cloud mode; the ServicePortal helpers are monkeypatched on auth_helper."""

    def test_single_subscription_logs_in(self, rest_api, monkeypatch) -> None:
        """One subscription auto-logs the user in and returns a token."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal',
                            lambda _u, _p: {'subscriptions': [{'id': 's1', 'name': 'Sub 1', 'database': 'db1'}]})
        monkeypatch.setattr(auth_helper, 'check_db_exists', lambda _db: True)
        monkeypatch.setattr(auth_helper, 'set_admin_user', lambda *_a, **_k: None)
        monkeypatch.setattr(auth_helper, 'retrieve_user', lambda *_a, **_k: _cloud_user())

        response = rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'})

        assert response.status_code == HTTPStatus.OK
        assert 'token' in response.get_json()

    def test_missing_db_is_initialised_then_logs_in(self, rest_api, monkeypatch) -> None:
        """A not-yet-existing subscription database is initialised before login."""
        _enable_cloud(rest_api, monkeypatch)
        init_calls: list[str] = []
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal',
                            lambda _u, _p: {'subscriptions': [{'id': 's1', 'name': 'Sub 1', 'database': 'db1'}]})
        monkeypatch.setattr(auth_helper, 'check_db_exists', lambda _db: False)
        monkeypatch.setattr(auth_helper, 'init_db_routine', init_calls.append)
        monkeypatch.setattr(auth_helper, 'set_admin_user', lambda *_a, **_k: None)
        monkeypatch.setattr(auth_helper, 'retrieve_user', lambda *_a, **_k: _cloud_user())

        response = rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'})

        assert response.status_code == HTTPStatus.OK
        assert init_calls == ['db1']

    def test_multiple_subscriptions_returns_choice_list(self, rest_api, monkeypatch) -> None:
        """Several subscriptions and none selected returns the list of options (no token)."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda _u, _p: {'subscriptions': [
            {'id': 's1', 'name': 'Sub 1', 'short_id': 'SID-1', 'database': 'db1'},
            {'id': 's2', 'name': 'Sub 2', 'database': 'db2'},
        ]})

        response = rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'})

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        # short_id is carried through (None when the subscription omits it)
        assert body == [
            {'id': 's1', 'name': 'Sub 1', 'short_id': 'SID-1'},
            {'id': 's2', 'name': 'Sub 2', 'short_id': None},
        ]

    def test_selected_subscription_logs_in(self, rest_api, monkeypatch) -> None:
        """A selected subscription (from several) logs the user into that database."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda _u, _p: {'subscriptions': [
            {'id': 's1', 'name': 'Sub 1', 'database': 'db1'},
            {'id': 's2', 'name': 'Sub 2', 'database': 'db2'},
        ]})
        monkeypatch.setattr(auth_helper, 'check_db_exists', lambda _db: True)
        monkeypatch.setattr(auth_helper, 'set_admin_user', lambda *_a, **_k: None)
        monkeypatch.setattr(auth_helper, 'retrieve_user', lambda *_a, **_k: _cloud_user())

        response = rest_api.post(
            LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw', 'subscription': {'id': 's2'}},
        )

        assert response.status_code == HTTPStatus.OK
        assert 'token' in response.get_json()

    def test_selected_subscription_not_found_returns_400(self, rest_api, monkeypatch) -> None:
        """Selecting a subscription id that does not exist is rejected with 400."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda _u, _p: {'subscriptions': [
            {'id': 's1', 'name': 'Sub 1', 'database': 'db1'},
            {'id': 's2', 'name': 'Sub 2', 'database': 'db2'},
        ]})

        response = rest_api.post(
            LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw', 'subscription': {'id': 'nope'}},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_no_subscriptions_returns_401(self, rest_api, monkeypatch) -> None:
        """A user with no subscriptions cannot log in (401)."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda _u, _p: {'subscriptions': []})

        assert rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'}).status_code \
            == HTTPStatus.UNAUTHORIZED

    def test_invalid_service_portal_user_returns_401(self, rest_api, monkeypatch) -> None:
        """A ServicePortal miss (None) maps to 401."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda _u, _p: None)

        assert rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'}).status_code \
            == HTTPStatus.UNAUTHORIZED

    def test_invalid_cloud_user_error_returns_403(self, rest_api, monkeypatch) -> None:
        """An InvalidCloudUserError from the ServicePortal maps to 403."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', _raiser(InvalidCloudUserError('boom')))

        assert rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'}).status_code \
            == HTTPStatus.FORBIDDEN

    def test_selected_subscription_missing_db_is_initialised(self, rest_api, monkeypatch) -> None:
        """The selected-subscription path initialises its database when absent, then logs in."""
        _enable_cloud(rest_api, monkeypatch)
        init_calls: list[str] = []
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda _u, _p: {'subscriptions': [
            {'id': 's1', 'name': 'Sub 1', 'database': 'db1'},
            {'id': 's2', 'name': 'Sub 2', 'database': 'db2'},
        ]})
        monkeypatch.setattr(auth_helper, 'check_db_exists', lambda _db: False)
        monkeypatch.setattr(auth_helper, 'init_db_routine', init_calls.append)
        monkeypatch.setattr(auth_helper, 'set_admin_user', lambda *_a, **_k: None)
        monkeypatch.setattr(auth_helper, 'retrieve_user', lambda *_a, **_k: _cloud_user())

        response = rest_api.post(
            LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw', 'subscription': {'id': 's2'}},
        )

        assert response.status_code == HTTPStatus.OK
        assert init_calls == ['db2']

    def test_user_not_found_in_database_returns_401(self, rest_api, monkeypatch) -> None:
        """A valid subscription but no matching user in the database responds 401."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', _single_subscription_portal)
        monkeypatch.setattr(auth_helper, 'check_db_exists', lambda _db: True)
        monkeypatch.setattr(auth_helper, 'set_admin_user', lambda *_a, **_k: None)
        monkeypatch.setattr(auth_helper, 'retrieve_user', lambda *_a, **_k: None)

        assert rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'}).status_code \
            == HTTPStatus.UNAUTHORIZED

    @pytest.mark.parametrize('exc', [
        NoAccessTokenError('boom'),
        RequestTimeoutError('boom'),
        DatabaseConnectionError('boom'),
        RequestError('boom'),
        RuntimeError('boom'),
    ])
    def test_service_portal_errors_map_to_500(self, rest_api, monkeypatch, exc) -> None:
        """The ServicePortal error family (and any unexpected error) maps to 500."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', _raiser(exc))

        assert rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'}).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize('exc', [UsersManagerGetError('boom'), UsersManagerInsertError('boom')])
    def test_user_retrieval_errors_map_to_500(self, rest_api, monkeypatch, exc) -> None:
        """A UsersManager error while retrieving the cloud user maps to 500."""
        _enable_cloud(rest_api, monkeypatch)
        monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', _single_subscription_portal)
        monkeypatch.setattr(auth_helper, 'check_db_exists', lambda _db: True)
        monkeypatch.setattr(auth_helper, 'set_admin_user', lambda *_a, **_k: None)
        monkeypatch.setattr(auth_helper, 'retrieve_user', _raiser(exc))

        assert rest_api.post(LOGIN_URL, json={'user_name': 'cloud@x.io', 'password': 'pw'}).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                            SETTINGS / PROVIDERS                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='restore_auth_section')
def fixture_restore_auth_section(database_manager: MongoDatabaseManager, database_name: str):
    """Puts the stored auth section back exactly as it was, or removes it if there was none."""
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    before = collection.find_one({'_id': AUTH_SETTINGS_SECTION})
    yield
    if before is None:
        collection.delete_one({'_id': AUTH_SETTINGS_SECTION})
    else:
        collection.replace_one({'_id': AUTH_SETTINGS_SECTION}, before, upsert=True)


class TestAuthSettingsAndProviders:
    """The /auth/settings and /auth/providers read + update routes."""

    def test_get_auth_settings_returns_200(self, rest_api) -> None:
        """GET /auth/settings returns the current auth settings."""
        assert rest_api.get(SETTINGS_URL).status_code == HTTPStatus.OK

    def test_get_auth_settings_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An error reading the auth settings surfaces as 500."""
        monkeypatch.setattr(SettingsManager, 'get_all_values_from_section', _raiser(RuntimeError('boom')))

        assert rest_api.get(SETTINGS_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_installed_providers_returns_list(self, rest_api) -> None:
        """GET /auth/providers returns a list of provider descriptors."""
        response = rest_api.get(PROVIDERS_URL)

        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.get_json(), list)

    def test_get_installed_providers_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An error while resolving providers surfaces as 500."""
        monkeypatch.setattr(SettingsManager, 'get_all_values_from_section', _raiser(RuntimeError('boom')))

        assert rest_api.get(PROVIDERS_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_provider_config_found(self, rest_api) -> None:
        """GET /auth/providers/<class> returns the config for an installed provider."""
        providers = rest_api.get(PROVIDERS_URL).get_json()
        class_name = providers[0]['class_name']

        assert rest_api.get(f'{PROVIDERS_URL}/{class_name}').status_code == HTTPStatus.OK

    def test_get_provider_config_missing_returns_404(self, rest_api) -> None:
        """An unknown provider class returns 404 (get_provider returns None -> guarded 404)."""
        assert rest_api.get(f'{PROVIDERS_URL}/NotARealProvider').status_code == HTTPStatus.NOT_FOUND

    def test_get_provider_config_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while resolving the provider surfaces as 500."""
        monkeypatch.setattr(AuthModule, 'get_provider', _raiser(RuntimeError('boom')))
        providers = rest_api.get(PROVIDERS_URL).get_json()
        class_name = providers[0]['class_name']

        assert rest_api.get(f'{PROVIDERS_URL}/{class_name}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---------------------------------------------------------------------------------------------- #
    #                            THE LDAP BIND PASSWORD IS NEVER SERVED                               #
    # ---------------------------------------------------------------------------------------------- #

    def test_get_auth_settings_masks_the_bind_password(self, rest_api) -> None:
        """`GET /auth/settings` never serves the LDAP bind credential in cleartext."""
        body = rest_api.get(SETTINGS_URL).get_json()
        ldap = next(entry for entry in body['providers'] if entry['class_name'] == LDAP_PROVIDER)

        assert ldap['config']['connection_config']['password'] == MASKED_SECRET

    def test_get_auth_settings_keeps_its_shape(self, rest_api) -> None:
        """Masking replaces one value; it does not reshape the response."""
        body = rest_api.get(SETTINGS_URL).get_json()

        assert {'_id', 'providers', 'enable_external', 'token_lifetime'} <= set(body)

    def test_get_provider_config_masks_the_bind_password(self, rest_api) -> None:
        """The second read path, which served the same credential through a different route."""
        body = rest_api.get(f'{PROVIDERS_URL}/{LDAP_PROVIDER}').get_json()

        assert body['connection_config']['password'] == MASKED_SECRET

    @pytest.mark.usefixtures('restore_auth_section')
    def test_the_real_password_survives_a_read_modify_write(self, rest_api) -> None:
        """
        The half that makes masking safe

        The update route takes the WHOLE section, so a client that reads the settings, changes one
        field and posts the object back sends the mask where the password was. It must resolve to the
        stored credential, not overwrite it with the mask - otherwise every LDAP login breaks.
        """
        settings_manager = SettingsManager(rest_api.application.database_manager)

        def _stored_password() -> str:
            stored = settings_manager.get_all_values_from_section(
                AUTH_SETTINGS_SECTION, default=AuthModule.__DEFAULT_SETTINGS__,
            )
            entry = next(item for item in stored['providers'] if item['class_name'] == LDAP_PROVIDER)

            return entry['config']['connection_config']['password']

        before = _stored_password()

        served = rest_api.get(SETTINGS_URL).get_json()
        served['token_lifetime'] = 4242

        assert rest_api.post(SETTINGS_URL, json=served).status_code == HTTPStatus.OK

        # The exact value, not merely "not the mask": the credential must come through unchanged
        assert _stored_password() == before
        assert before != MASKED_SECRET
        assert settings_manager.get_all_values_from_section(AUTH_SETTINGS_SECTION)['token_lifetime'] == 4242

    @pytest.mark.usefixtures('restore_auth_section')
    def test_a_deliberate_password_change_is_written(self, rest_api) -> None:
        """A real value at the secret path is a change, not a mask, and must be stored."""
        served = rest_api.get(SETTINGS_URL).get_json()
        ldap = next(entry for entry in served['providers'] if entry['class_name'] == LDAP_PROVIDER)
        ldap['config']['connection_config']['password'] = 'a-deliberately-new-password'

        assert rest_api.post(SETTINGS_URL, json=served).status_code == HTTPStatus.OK

        stored = SettingsManager(
            rest_api.application.database_manager,
        ).get_all_values_from_section(AUTH_SETTINGS_SECTION)
        stored_ldap = next(entry for entry in stored['providers'] if entry['class_name'] == LDAP_PROVIDER)

        assert stored_ldap['config']['connection_config']['password'] == 'a-deliberately-new-password'

    @pytest.mark.usefixtures('restore_auth_section')
    def test_the_update_response_is_masked_too(self, rest_api) -> None:
        """The update echoes the stored section back, which is a third read of the same credential."""
        served = rest_api.get(SETTINGS_URL).get_json()
        body = rest_api.post(SETTINGS_URL, json=served).get_json()
        ldap = next(entry for entry in body['providers'] if entry['class_name'] == LDAP_PROVIDER)

        assert ldap['config']['connection_config']['password'] == MASKED_SECRET

    def test_update_auth_settings_no_body_returns_400(self, rest_api) -> None:
        """An empty update body is rejected with 400."""
        assert rest_api.post(SETTINGS_URL, json={}).status_code == HTTPStatus.BAD_REQUEST

    def test_update_auth_settings_init_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A payload that fails CmdbAuthSettings validation is a client error -> 400."""
        monkeypatch.setattr(auth_routes.CmdbAuthSettings, 'from_data', _raiser(AuthSettingsInitError('boom')))

        assert rest_api.post(SETTINGS_URL, json={'providers': []}).status_code == HTTPStatus.BAD_REQUEST

    def test_update_auth_settings_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while building the settings surfaces as 500."""
        monkeypatch.setattr(auth_routes.CmdbAuthSettings, 'from_data', _raiser(RuntimeError('boom')))

        assert rest_api.post(SETTINGS_URL, json={'providers': []}).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_auth_settings_not_acknowledged_returns_400(self, rest_api, monkeypatch) -> None:
        """When the settings write is not acknowledged, the route responds 400."""
        class _UnacknowledgedResult:
            """Stand-in write result reporting a non-acknowledged write."""
            acknowledged = False

        monkeypatch.setattr(SettingsManager, 'write', lambda *_a, **_k: _UnacknowledgedResult())

        assert rest_api.post(SETTINGS_URL, json={'providers': [], 'enable_external': False,
                                                 'token_lifetime': 1440}).status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.usefixtures('restore_auth_section')
    def test_update_auth_settings_success(self, rest_api) -> None:
        """A valid update persists and echoes the auth settings; the section is restored afterwards."""
        response = rest_api.post(SETTINGS_URL, json={'providers': [], 'enable_external': False,
                                                     'token_lifetime': 1440})

        assert response.status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                         THE LOCAL PROVIDER'S ACTIVE FLAG                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def _local_entry(body: dict) -> dict:
    """The local provider's entry of an auth settings body."""
    return next(entry for entry in body['providers'] if entry['class_name'] == LOCAL_PROVIDER)


@pytest.mark.usefixtures('restore_auth_section')
class TestLocalProviderActiveFlag:
    """A local config stored without its flag is served as active, not as `active: null`."""

    @pytest.mark.parametrize('local_config', [{}, {PROVIDER_ACTIVE_KEY: None}], ids=['missing', 'null'])
    def test_a_saved_config_without_a_flag_reads_back_active(self, rest_api, local_config: dict) -> None:
        """The settings page shows this checkbox and posts it back, so a null would keep itself alive."""
        served = rest_api.get(SETTINGS_URL).get_json()
        _local_entry(served)['config'] = local_config

        assert rest_api.post(SETTINGS_URL, json=served).status_code == HTTPStatus.OK

        assert _local_entry(rest_api.get(SETTINGS_URL).get_json())['config'][PROVIDER_ACTIVE_KEY] is True

    def test_the_provider_config_route_reads_it_active_too(self, rest_api) -> None:
        """The second read path builds the provider, and its config, the same way."""
        served = rest_api.get(SETTINGS_URL).get_json()
        _local_entry(served)['config'] = {}
        rest_api.post(SETTINGS_URL, json=served)

        body = rest_api.get(f'{PROVIDERS_URL}/{LOCAL_PROVIDER}').get_json()

        assert body[PROVIDER_ACTIVE_KEY] is True

    def test_login_works_with_the_local_provider_configured_inactive(self, rest_api) -> None:
        """Local login is the way back in: a stored False does not lock the admin out."""
        served = rest_api.get(SETTINGS_URL).get_json()
        _local_entry(served)['config'] = {PROVIDER_ACTIVE_KEY: False}
        rest_api.post(SETTINGS_URL, json=served)

        response = rest_api.post(LOGIN_URL, json={'user_name': 'admin', 'password': 'admin'})

        assert response.status_code == HTTPStatus.OK
