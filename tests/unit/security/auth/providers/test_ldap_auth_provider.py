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
Unit tests for cmdb.security.auth.providers.ldap_auth_provider

DB-free and directory-free: `Server` and `Connection` are patched at the provider's module path and the
UsersManager is a MagicMock, so the whole authentication flow is exercised without an LDAP server.

The service-account connection (built in `__init__`) and the per-login user connection (built to verify
the password) are told apart by the number of positional arguments the provider passes, so each can be
asserted on separately - which is what makes the bind / unbind expectations meaningful.

Covered beyond the happy path: the credential guards (an empty password must never reach a bind), the
filter escaping, the single-entry rule, the group mapping by DN and by CN, and every way the local
CmdbUser sync can fail - including the one that used to provision a duplicate user.
"""
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ldap3.core.exceptions import LDAPExceptionError

from cmdb.models.user_model import CmdbUser
from cmdb.errors.provider import AuthenticationError
from cmdb.errors.manager.users_manager import (
    UsersManagerGetError,
    UsersManagerInsertError,
    UsersManagerUpdateError,
)
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.ldap_constants import ProvisionedUserKey
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.security.auth.providers.ldap_auth_provider'

USER_NAME: str = 'alice'
PASSWORD: str = 'secret'
USER_DN: str = 'uid=alice,ou=people,dc=example,dc=com'
OTHER_USER_DN: str = 'uid=alice,ou=service,dc=example,dc=com'

ADMIN_GROUP_DN: str = 'cn=admins,ou=groups,dc=example,dc=com'
ADMIN_GROUP_CN: str = 'admins'

DEFAULT_GROUP_ID: int = 2
MAPPED_GROUP_ID: int = 7
STORED_USER_ID: int = 42
NEW_USER_ID: int = 43

BASE_DN: str = 'dc=example,dc=com'
USER_FILTER: str = '(uid=%username%)'
GROUP_FILTER: str = '(memberUid=%username%)'

# A login name that would rewrite the filter it is substituted into if it were not escaped
INJECTING_USER_NAME: str = 'alice)(uid=*'


def _settings(**overrides: Any) -> dict[str, Any]:
    """Builds the stored provider settings, with the group mapping switched off by default."""
    settings: dict[str, Any] = {
        'active': True,
        'default_group': DEFAULT_GROUP_ID,
        'server_config': {'host': 'ldap.example.com', 'port': 389, 'use_ssl': False},
        'connection_config': {'user': 'cn=reader,dc=example,dc=com', 'password': 'reader-pw', 'version': 3},
        'search': {'basedn': BASE_DN, 'searchfilter': USER_FILTER},
        'groups': {'active': False, 'searchfiltergroup': GROUP_FILTER, 'mapping': []},
    }
    settings.update(overrides)

    return settings


def _entry(entry_dn: str) -> MagicMock:
    """A search result entry, of which the provider only reads the DN."""
    entry = MagicMock()
    entry.entry_dn = entry_dn

    return entry


def _stored_user(group_id: int = DEFAULT_GROUP_ID) -> CmdbUser:
    """A CmdbUser as the UsersManager would hand it back."""
    return CmdbUser.from_data({
        'public_id': STORED_USER_ID,
        'user_name': USER_NAME,
        'active': True,
        'group_id': group_id,
        'authenticator': 'LdapAuthenticationProvider',
    })


@pytest.fixture(name='ldap')
def ldap_fixture():
    """
    Patches Server/Connection and yields the doubles plus a provider builder

    `service` is the connection built in __init__ (one positional argument: the server); `user` is the
    one built to verify a password (three: server, dn, password). The factory tells them apart by that,
    so a test can assert on either without them bleeding into each other.
    """
    with patch(f'{MODULE_PATH}.Server') as server_factory, \
         patch(f'{MODULE_PATH}.Connection') as connection_factory:
        service_connection = MagicMock(name='service_connection')
        service_connection.bind.return_value = True
        service_connection.search.return_value = True
        service_connection.entries = [_entry(USER_DN)]

        user_connection = MagicMock(name='user_connection')

        def _connection(*args: Any, **_kwargs: Any) -> MagicMock:
            return service_connection if len(args) == 1 else user_connection

        connection_factory.side_effect = _connection

        users_manager = MagicMock(name='users_manager')
        users_manager.get_user_by.return_value = _stored_user()

        def _build(**overrides: Any) -> LdapAuthenticationProvider:
            config = LdapAuthenticationProviderConfig(**_settings(**overrides))

            return LdapAuthenticationProvider(
                config=config, security_manager=MagicMock(), users_manager=users_manager,
            )

        yield SimpleNamespace(
            server_factory=server_factory,
            connection_factory=connection_factory,
            service=service_connection,
            user=user_connection,
            users_manager=users_manager,
            build=_build,
        )


def _group_settings(mapping: list[dict[str, Any]], active: bool = True) -> dict[str, Any]:
    """Group settings with mapping switched on."""
    return {'groups': {'active': active, 'searchfiltergroup': GROUP_FILTER, 'mapping': mapping}}


class TestInitialisation:
    """The provider derives its server and service connection from the configuration."""

    def test_builds_server_and_connection_from_the_config(self, ldap) -> None:
        """Both config blocks are forwarded to ldap3 unchanged."""
        ldap.build()

        ldap.server_factory.assert_called_once_with(host='ldap.example.com', port=389, use_ssl=False)
        assert ldap.connection_factory.call_args.kwargs == {
            'user': 'cn=reader,dc=example,dc=com', 'password': 'reader-pw', 'version': 3,
        }

    def test_works_without_a_config(self, ldap) -> None:
        """The documented `config=None` builds the provider defaults instead of raising (regression)."""
        provider = LdapAuthenticationProvider()

        assert isinstance(provider.get_config(), LdapAuthenticationProviderConfig)
        ldap.server_factory.assert_called_once()

    @pytest.mark.parametrize('active', [True, False], ids=['active', 'inactive'])
    def test_is_active_follows_the_config(self, ldap, active: bool) -> None:
        """AuthModule skips the provider when it is deactivated, so this must mirror the setting."""
        assert ldap.build(active=active).is_active() is active


class TestConnectionLifecycle:
    """The service-account connection is bound per login and always released again."""

    def test_connect_delegates_to_the_bind(self, ldap) -> None:
        """connect() returns whatever ldap3's bind reports."""
        ldap.service.bind.return_value = False

        assert ldap.build().connect() is False
        ldap.service.bind.assert_called_once_with()

    def test_disconnect_unbinds(self, ldap) -> None:
        """disconnect() releases the connection - nothing else in the codebase does (regression)."""
        ldap.build().disconnect()

        ldap.service.unbind.assert_called_once_with()

    def test_disconnect_swallows_an_unbind_failure(self, ldap) -> None:
        """The login outcome is already decided, so a failing unbind must not raise."""
        ldap.service.unbind.side_effect = LDAPExceptionError('gone')

        ldap.build().disconnect()

    def test_context_manager_releases_the_connection(self, ldap) -> None:
        """`with provider:` now works - __exit__ used to exist without an __enter__."""
        provider = ldap.build()

        with provider as entered:
            assert entered is provider

        ldap.service.unbind.assert_called_once_with()

    def test_a_successful_login_releases_the_connection(self, ldap) -> None:
        """The service connection is unbound on the success path too."""
        ldap.build().authenticate(USER_NAME, PASSWORD)

        ldap.service.unbind.assert_called_once_with()

    def test_a_failed_login_releases_the_connection(self, ldap) -> None:
        """A refused login must not leak the bound connection either."""
        ldap.service.entries = []

        with pytest.raises(AuthenticationError):
            ldap.build().authenticate(USER_NAME, PASSWORD)

        ldap.service.unbind.assert_called_once_with()


class TestCredentialGuards:
    """Unusable credentials are refused before the directory is contacted at all."""

    @pytest.mark.parametrize('password', ['', '   ', None], ids=['empty', 'blank', 'none'])
    def test_an_empty_password_never_reaches_a_bind(self, ldap, password: Any) -> None:
        """An empty password would be an unauthenticated simple bind some directories accept."""
        with pytest.raises(AuthenticationError) as exc_info:
            ldap.build().authenticate(USER_NAME, password)

        assert 'No password' in str(exc_info.value)
        ldap.service.bind.assert_not_called()
        ldap.service.search.assert_not_called()

    @pytest.mark.parametrize('user_name', ['', '  ', None], ids=['empty', 'blank', 'none'])
    def test_a_blank_user_name_is_refused(self, ldap, user_name: Any) -> None:
        """Without a name there is nothing to search for - it must not become an empty filter."""
        with pytest.raises(AuthenticationError):
            ldap.build().authenticate(user_name, PASSWORD)

        ldap.service.bind.assert_not_called()


class TestServiceAccountBind:
    """The search runs through the configured service account."""

    def test_a_refused_bind_is_an_authentication_error(self, ldap) -> None:
        """bind() returning False means the provider cannot search at all."""
        ldap.service.bind.return_value = False

        with pytest.raises(AuthenticationError) as exc_info:
            ldap.build().authenticate(USER_NAME, PASSWORD)

        assert 'Could not connect' in str(exc_info.value)

    def test_a_raising_bind_is_an_authentication_error(self, ldap) -> None:
        """An ldap3 error is reported with its detail, so AuthModule can fall back."""
        ldap.service.bind.side_effect = LDAPExceptionError('host down')

        with pytest.raises(AuthenticationError) as exc_info:
            ldap.build().authenticate(USER_NAME, PASSWORD)

        assert 'host down' in str(exc_info.value)


class TestUserLookup:
    """The login name is escaped, and exactly one entry has to match."""

    def test_searches_the_configured_base_with_the_filled_filter(self, ldap) -> None:
        """The configured filter and base DN are used as-is, with the name substituted."""
        ldap.build().authenticate(USER_NAME, PASSWORD)

        ldap.service.search.assert_called_once_with(BASE_DN, f'(uid={USER_NAME})')

    def test_escapes_the_login_name(self, ldap) -> None:
        """An unescaped name would rewrite the filter it is substituted into (regression)."""
        ldap.service.entries = [_entry(USER_DN)]

        ldap.build().authenticate(INJECTING_USER_NAME, PASSWORD)

        used_filter = ldap.service.search.call_args_list[0].args[1]

        assert '(uid=*' not in used_filter
        assert used_filter == '(uid=alice\\29\\28uid=\\2a)'

    @pytest.mark.parametrize('found, entries', [(True, []), (False, [_entry(USER_DN)])],
                             ids=['no-entries', 'search-failed'])
    def test_no_match_is_refused(self, ldap, found: bool, entries: list) -> None:
        """Neither an empty result nor a failed search may authenticate anyone."""
        ldap.service.search.return_value = found
        ldap.service.entries = entries

        with pytest.raises(AuthenticationError) as exc_info:
            ldap.build().authenticate(USER_NAME, PASSWORD)

        assert 'No matching entry' in str(exc_info.value)

    def test_an_ambiguous_match_is_refused_without_binding(self, ldap) -> None:
        """Two matches used to bind BOTH DNs; guessing which one was meant decides who you become."""
        ldap.service.entries = [_entry(USER_DN), _entry(OTHER_USER_DN)]

        with pytest.raises(AuthenticationError) as exc_info:
            ldap.build().authenticate(USER_NAME, PASSWORD)

        assert 'matched 2 entries' in str(exc_info.value)
        # only the service connection was ever built
        assert all(len(call.args) == 1 for call in ldap.connection_factory.call_args_list)


class TestPasswordVerification:
    """The password is proven by binding the found entry."""

    def test_binds_the_found_entry_with_the_submitted_password(self, ldap) -> None:
        """This bind IS the authentication - the search only located the DN."""
        ldap.build().authenticate(USER_NAME, PASSWORD)

        user_call = ldap.connection_factory.call_args_list[-1]

        assert user_call.args[1:] == (USER_DN, PASSWORD)
        assert user_call.kwargs == {'auto_bind': True}

    def test_releases_the_user_connection(self, ldap) -> None:
        """The check connection exists only for the bind and is unbound right away."""
        ldap.build().authenticate(USER_NAME, PASSWORD)

        ldap.user.unbind.assert_called_once_with()

    def test_a_failing_user_unbind_is_swallowed(self, ldap) -> None:
        """The password was already accepted, so a failing release must not fail the login."""
        ldap.user.unbind.side_effect = LDAPExceptionError('gone')

        assert ldap.build().authenticate(USER_NAME, PASSWORD) is not None

    def test_a_refused_bind_is_an_authentication_error(self, ldap) -> None:
        """A wrong password is reported with the directory's own detail."""
        ldap.connection_factory.side_effect = None
        ldap.connection_factory.return_value = ldap.service
        provider = ldap.build()
        ldap.connection_factory.side_effect = LDAPExceptionError('invalidCredentials')

        with pytest.raises(AuthenticationError) as exc_info:
            provider.authenticate(USER_NAME, PASSWORD)

        assert 'invalidCredentials' in str(exc_info.value)

    def test_no_group_search_when_the_password_is_wrong(self, ldap) -> None:
        """The group is resolved only after the password was accepted."""
        ldap.connection_factory.side_effect = None
        ldap.connection_factory.return_value = ldap.service
        provider = ldap.build(**_group_settings([{'group_dn': ADMIN_GROUP_DN, 'group_id': MAPPED_GROUP_ID}]))
        ldap.connection_factory.side_effect = LDAPExceptionError('invalidCredentials')

        with pytest.raises(AuthenticationError):
            provider.authenticate(USER_NAME, PASSWORD)

        assert ldap.service.search.call_count == 1  # the user search only


class TestGroupResolution:
    """The mapped group is optional and never decides whether a login succeeds."""

    def test_mapping_disabled_uses_the_default_group(self, ldap) -> None:
        """With group mapping off no group search is issued at all."""
        ldap.build().authenticate(USER_NAME, PASSWORD)

        assert ldap.service.search.call_count == 1
        ldap.users_manager.update_user.assert_not_called()

    def test_no_group_entries_falls_back_to_the_default_group(self, ldap) -> None:
        """A user in no mapped group keeps the default group instead of being refused."""
        ldap.users_manager.get_user_by.return_value = None
        ldap.users_manager.get_user.return_value = _stored_user()
        ldap.service.search.side_effect = [True, False]

        ldap.build(**_group_settings([{'group_dn': ADMIN_GROUP_DN, 'group_id': MAPPED_GROUP_ID}]))\
            .authenticate(USER_NAME, PASSWORD)

        created = ldap.users_manager.insert_user.call_args.args[0]

        assert created[ProvisionedUserKey.GROUP_ID.value] == DEFAULT_GROUP_ID

    @pytest.mark.parametrize(
        'configured_dn',
        [ADMIN_GROUP_DN, ADMIN_GROUP_DN.upper(), ADMIN_GROUP_CN],
        ids=['full-dn', 'full-dn-other-case', 'bare-cn'],
    )
    def test_maps_a_group_by_dn_or_cn(self, ldap, configured_dn: str) -> None:
        """The settings UI asks for a DN; the CN stays accepted for installations configured that way."""
        ldap.service.entries = [_entry(USER_DN)]
        ldap.service.search.side_effect = self._group_search(ldap, [_entry(ADMIN_GROUP_DN)])
        ldap.users_manager.get_user_by.return_value = _stored_user()

        provider = ldap.build(**_group_settings([{'group_dn': configured_dn, 'group_id': MAPPED_GROUP_ID}]))
        provider.authenticate(USER_NAME, PASSWORD)

        updated = ldap.users_manager.update_user.call_args.args[1]

        assert updated.group_id == MAPPED_GROUP_ID

    def test_a_malformed_group_dn_does_not_break_the_login(self, ldap) -> None:
        """A DN the CN pattern does not fit used to raise an AttributeError out of authenticate."""
        ldap.service.search.side_effect = self._group_search(ldap, [_entry('malformed-dn')])
        ldap.users_manager.get_user_by.return_value = _stored_user()

        provider = ldap.build(**_group_settings([{'group_dn': ADMIN_GROUP_DN, 'group_id': MAPPED_GROUP_ID}]))
        provider.authenticate(USER_NAME, PASSWORD)

        ldap.users_manager.update_user.assert_not_called()  # stayed on the default group

    def test_an_unusable_group_id_is_skipped(self, ldap) -> None:
        """A mapping whose group_id is not a number is a config mistake, not a login failure."""
        ldap.service.search.side_effect = self._group_search(ldap, [_entry(ADMIN_GROUP_DN)])
        ldap.users_manager.get_user_by.return_value = _stored_user()

        provider = ldap.build(**_group_settings([{'group_dn': ADMIN_GROUP_DN, 'group_id': 'not-a-number'}]))
        provider.authenticate(USER_NAME, PASSWORD)

        ldap.users_manager.update_user.assert_not_called()

    def test_an_empty_mapping_keeps_the_default_group(self, ldap) -> None:
        """Group search on, nothing configured to map: the default group applies."""
        ldap.service.search.side_effect = self._group_search(ldap, [_entry(ADMIN_GROUP_DN)])
        ldap.users_manager.get_user_by.return_value = _stored_user()

        ldap.build(**_group_settings([])).authenticate(USER_NAME, PASSWORD)

        ldap.users_manager.update_user.assert_not_called()

    @staticmethod
    def _group_search(ldap, group_entries: list) -> Any:
        """Search side effect: the user search first, then the group search with the given entries."""
        def _search(*_args: Any, **_kwargs: Any) -> bool:
            if ldap.service.search.call_count > 1:
                ldap.service.entries = group_entries
            else:
                ldap.service.entries = [_entry(USER_DN)]

            return True

        return _search


class TestLocalUserSync:
    """The authenticated directory user is matched to - or provisioned as - a CmdbUser."""

    def test_returns_the_stored_user(self, ldap) -> None:
        """A known user with an up-to-date group is handed back untouched."""
        stored = _stored_user()
        ldap.users_manager.get_user_by.return_value = stored

        assert ldap.build().authenticate(USER_NAME, PASSWORD) is stored
        ldap.users_manager.update_user.assert_not_called()
        ldap.users_manager.insert_user.assert_not_called()

    def test_a_failing_read_is_an_authentication_error(self, ldap) -> None:
        """A database problem must not be mistaken for 'this user does not exist here'."""
        ldap.users_manager.get_user_by.side_effect = UsersManagerGetError('db down')

        with pytest.raises(AuthenticationError) as exc_info:
            ldap.build().authenticate(USER_NAME, PASSWORD)

        assert 'db down' in str(exc_info.value)
        ldap.users_manager.insert_user.assert_not_called()

    def test_applies_the_mapped_group_without_a_second_read(self, ldap) -> None:
        """The written instance is returned as-is, so the update costs one query, not two."""
        stored = _stored_user()
        ldap.users_manager.get_user_by.return_value = stored
        ldap.service.search.side_effect = TestGroupResolution._group_search(ldap, [_entry(ADMIN_GROUP_DN)])

        provider = ldap.build(**_group_settings([{'group_dn': ADMIN_GROUP_DN, 'group_id': MAPPED_GROUP_ID}]))
        result = provider.authenticate(USER_NAME, PASSWORD)

        assert result.group_id == MAPPED_GROUP_ID
        ldap.users_manager.update_user.assert_called_once()
        ldap.users_manager.get_user_by.assert_called_once()

    def test_a_failing_group_update_does_not_provision_a_duplicate(self, ldap) -> None:
        """The regression: the update error used to be swallowed and the user created a second time."""
        ldap.users_manager.get_user_by.return_value = _stored_user()
        ldap.users_manager.update_user.side_effect = UsersManagerUpdateError('write failed')
        ldap.service.search.side_effect = TestGroupResolution._group_search(ldap, [_entry(ADMIN_GROUP_DN)])

        provider = ldap.build(**_group_settings([{'group_dn': ADMIN_GROUP_DN, 'group_id': MAPPED_GROUP_ID}]))

        with pytest.raises(AuthenticationError) as exc_info:
            provider.authenticate(USER_NAME, PASSWORD)

        assert 'mapped group' in str(exc_info.value)
        ldap.users_manager.insert_user.assert_not_called()

    def test_provisions_an_unknown_user(self, ldap) -> None:
        """A user the directory knows but this installation does not is created, without a password."""
        created_user = _stored_user()
        ldap.users_manager.get_user_by.return_value = None
        ldap.users_manager.insert_user.return_value = NEW_USER_ID
        ldap.users_manager.get_user.return_value = created_user

        assert ldap.build().authenticate(USER_NAME, PASSWORD) is created_user

        new_user_data = ldap.users_manager.insert_user.call_args.args[0]

        assert set(new_user_data) == {key.value for key in ProvisionedUserKey}
        assert new_user_data[ProvisionedUserKey.USER_NAME.value] == USER_NAME
        assert new_user_data[ProvisionedUserKey.ACTIVE.value] is True
        assert new_user_data[ProvisionedUserKey.GROUP_ID.value] == DEFAULT_GROUP_ID
        assert new_user_data[ProvisionedUserKey.AUTHENTICATOR.value] == 'LdapAuthenticationProvider'
        assert isinstance(new_user_data[ProvisionedUserKey.REGISTRATION_TIME.value], datetime)
        ldap.users_manager.get_user.assert_called_once_with(NEW_USER_ID)

    def test_a_failing_insert_is_an_authentication_error(self, ldap) -> None:
        """A user that could not be created must not be reported as logged in."""
        ldap.users_manager.get_user_by.return_value = None
        ldap.users_manager.insert_user.side_effect = UsersManagerInsertError('duplicate')

        with pytest.raises(AuthenticationError) as exc_info:
            ldap.build().authenticate(USER_NAME, PASSWORD)

        assert 'Could not create' in str(exc_info.value)

    def test_a_failing_read_back_is_an_authentication_error(self, ldap) -> None:
        """The created user has to be readable - the caller receives a CmdbUser, not an id."""
        ldap.users_manager.get_user_by.return_value = None
        ldap.users_manager.insert_user.return_value = NEW_USER_ID
        ldap.users_manager.get_user.side_effect = UsersManagerGetError('db down')

        with pytest.raises(AuthenticationError):
            ldap.build().authenticate(USER_NAME, PASSWORD)

    def test_an_unreadable_created_user_is_an_authentication_error(self, ldap) -> None:
        """A read-back that finds nothing is refused instead of returning None as the user."""
        ldap.users_manager.get_user_by.return_value = None
        ldap.users_manager.insert_user.return_value = NEW_USER_ID
        ldap.users_manager.get_user.return_value = None

        with pytest.raises(AuthenticationError) as exc_info:
            ldap.build().authenticate(USER_NAME, PASSWORD)

        assert 'could not be read' in str(exc_info.value)


class TestFilterAndDnHelpers:
    """The two pure helpers behind the escaping and the group matching."""

    @pytest.mark.parametrize(
        'user_name, expected',
        [
            (USER_NAME, f'(uid={USER_NAME})'),
            ('a*b', '(uid=a\\2ab)'),
            ('a(b)c', '(uid=a\\28b\\29c)'),
            ('a\\b', '(uid=a\\5cb)'),
        ],
        ids=['plain', 'asterisk', 'parentheses', 'backslash'],
    )
    def test_build_filter_escapes_the_name(self, user_name: str, expected: str) -> None:
        """Every character with a meaning in an LDAP filter is escaped before substitution."""
        assert LdapAuthenticationProvider._build_filter(USER_FILTER, user_name) == expected

    def test_build_filter_leaves_a_filter_without_the_placeholder_alone(self) -> None:
        """A filter that does not name the placeholder is passed through unchanged."""
        assert LdapAuthenticationProvider._build_filter('(objectClass=*)', USER_NAME) == '(objectClass=*)'

    @pytest.mark.parametrize(
        'group_dns, expected',
        [
            ([ADMIN_GROUP_DN], {ADMIN_GROUP_CN}),
            (['CN=Admins,ou=groups,dc=example,dc=com'], {ADMIN_GROUP_CN}),
            (['malformed-dn'], set()),
            (['cn=admins'], set()),
            ([], set()),
        ],
        ids=['dn', 'upper-case-dn', 'no-separators', 'no-comma', 'empty'],
    )
    def test_extract_group_cns(self, group_dns: list[str], expected: set[str]) -> None:
        """The CN is read out where the pattern fits and the DN is skipped where it does not."""
        assert LdapAuthenticationProvider._extract_group_cns(group_dns) == expected
