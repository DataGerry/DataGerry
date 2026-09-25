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
Unit tests for the authentication provider configuration classes

`BaseAuthProviderConfig` turns a stored config sub-document into an object by setting every key it
was given as an attribute, and `LdapAuthenticationProviderConfig` adds the group-DN lookup the LDAP
login performs after a successful bind.

Both halves matter to `AuthModule.__init_settings`, which parses a stored config through the
provider's config class and falls back to that provider's defaults when the parse raises - so what
these classes accept decides whether an administrator's saved LDAP settings survive an upgrade.
"""
import pytest

from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig

from cmdb.errors.provider import GroupMappingError
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_DN: str = 'cn=cmdb-admins,ou=groups,dc=example,dc=com'
OTHER_GROUP_DN: str = 'cn=cmdb-users,ou=groups,dc=example,dc=com'
GROUP_ID: int = 7
OTHER_GROUP_ID: int = 8


def _ldap_config(mapping: list[dict] | None = None) -> LdapAuthenticationProviderConfig:
    """An LDAP config carrying the given group mapping and otherwise its defaults."""
    values = dict(LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES)
    values['groups'] = {**values['groups'], 'mapping': mapping if mapping is not None else []}

    return LdapAuthenticationProviderConfig(**values)


class TestBaseAuthProviderConfig:
    """
    Every key of the stored sub-document becomes an attribute

    `no-member` is disabled for this class: the attributes under test are set by `setattr` in the
    constructor, so by construction pylint cannot see them - which is the behaviour being pinned.
    """
    # pylint: disable=no-member

    def test_the_active_flag_is_a_named_parameter(self) -> None:
        """It is the one key every provider config has, so it is not left to the kwargs sweep."""
        assert BaseAuthProviderConfig(active=True).is_active() is True

    def test_extra_keys_become_attributes(self) -> None:
        """
        This is how a provider's own settings reach its config object

        The base class knows nothing about `server_config` or `search`; they arrive as kwargs and
        are set verbatim, which is what lets a subclass read them off `self`.
        """
        config = BaseAuthProviderConfig(active=False, host='ldap.example.com', port=389)

        assert config.host == 'ldap.example.com'
        assert config.port == 389

    def test_no_extra_keys_is_valid(self) -> None:
        """A provider with no configuration beyond the flag must still construct."""
        assert BaseAuthProviderConfig(active=False).is_active() is False

    def test_an_extra_key_does_not_displace_the_flag(self) -> None:
        """A stored document carrying a stray key must not shadow the one field that is declared."""
        config = BaseAuthProviderConfig(active=True, unexpected='value')

        assert config.is_active() is True
        assert config.unexpected == 'value'


class TestLdapConstruction:
    """What the LDAP configuration accepts beyond its declared keys"""

    def test_an_undeclared_stored_key_is_accepted_and_dropped(self) -> None:
        """A settings document with an extra key still loads; the key is not set as an attribute."""
        values = {**LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES, 'retired_option': True}

        config = LdapAuthenticationProviderConfig(**values)

        assert not hasattr(config, 'retired_option')

    def test_positional_arguments_beyond_the_declared_ones_are_refused(self) -> None:
        """Nothing absorbs a stray positional value any more, so a mis-ordered call fails loudly."""
        with pytest.raises(TypeError):
            LdapAuthenticationProviderConfig(True, 2, {}, {}, {}, {}, 'stray')  # pylint: disable=too-many-function-args


class TestLdapGroupMapping:
    """Resolving an LDAP group DN to the DataGerry group a user lands in."""

    def test_maps_a_known_group_dn(self) -> None:
        """The mapped id is what the provider assigns the user on a successful bind."""
        config = _ldap_config([{'group_dn': GROUP_DN, 'group_id': GROUP_ID}])

        assert config.mapping(GROUP_DN) == GROUP_ID

    def test_the_lookup_ignores_case(self) -> None:
        """A DN is case-insensitive, and directories do not agree on how to spell one."""
        config = _ldap_config([{'group_dn': GROUP_DN.upper(), 'group_id': GROUP_ID}])

        assert config.mapping(GROUP_DN.lower()) == GROUP_ID

    def test_the_first_match_wins(self) -> None:
        """Two entries for one DN is a misconfiguration; the answer still has to be deterministic."""
        config = _ldap_config([
            {'group_dn': GROUP_DN, 'group_id': GROUP_ID},
            {'group_dn': GROUP_DN, 'group_id': OTHER_GROUP_ID},
        ])

        assert config.mapping(GROUP_DN) == GROUP_ID

    def test_a_string_group_id_is_coerced(self) -> None:
        """The mapping is edited in a web form, so the id arrives as a string."""
        config = _ldap_config([{'group_dn': GROUP_DN, 'group_id': str(GROUP_ID)}])

        assert config.mapping(GROUP_DN) == GROUP_ID

    def test_an_unmapped_group_dn_is_refused(self) -> None:
        """
        The caller has to be able to tell "no mapping" from "mapped to group 0"

        Silently answering a default group would put an LDAP user into a group nobody assigned them
        to, which is the one outcome a group mapping exists to prevent.
        """
        config = _ldap_config([{'group_dn': OTHER_GROUP_DN, 'group_id': OTHER_GROUP_ID}])

        with pytest.raises(GroupMappingError):
            config.mapping(GROUP_DN)

    def test_an_empty_mapping_refuses_every_dn(self) -> None:
        """The default configuration ships with no mapping at all."""
        with pytest.raises(GroupMappingError):
            _ldap_config().mapping(GROUP_DN)
