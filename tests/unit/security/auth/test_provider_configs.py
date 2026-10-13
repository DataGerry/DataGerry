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
from copy import deepcopy
from typing import Any

import pytest

from cmdb.security.auth.base_provider_config import (
    FLAG_NOT_BOOLEAN_MSG,
    PROVIDER_ACTIVE_KEY,
    BaseAuthProviderConfig,
    validated_flag,
)
from cmdb.security.auth.providers.local_auth_config import LocalAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_auth_config import (
    GROUPS_ACTIVE_FLAG,
    GROUPS_NOT_AN_OBJECT_MSG,
    LdapAuthenticationProviderConfig,
)
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.ldap_constants import LdapGroupsKey

from cmdb.errors.provider import GroupMappingError, ProviderConfigError
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_DN: str = 'cn=cmdb-admins,ou=groups,dc=example,dc=com'
OTHER_GROUP_DN: str = 'cn=cmdb-users,ou=groups,dc=example,dc=com'
GROUP_ID: int = 7
OTHER_GROUP_ID: int = 8
FLAG_KEY: str = 'some_flag'
LDAP_HOST: str = 'ldap.example.com'

# Values a flag may arrive as that are no boolean - the strings among them truthy, whatever they spell
NOT_BOOLEANS: list[Any] = ['false', 'true', '0', '', 'no', 0, 1, [], {}, 0.0]


def _not_boolean_message(key: str, value: Any) -> str:
    """The refusal of a flag that is no boolean"""
    return FLAG_NOT_BOOLEAN_MSG.format(key=key, kind=type(value).__name__)


def _ldap_config(mapping: list[dict] | None = None) -> LdapAuthenticationProviderConfig:
    """An LDAP config carrying the given group mapping and otherwise its defaults."""
    values = dict(LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES)
    values['groups'] = {**values['groups'], 'mapping': mapping if mapping is not None else []}

    return LdapAuthenticationProviderConfig(**values)


class TestValidatedFlag:
    """validated_flag: only a real boolean is a flag"""

    @pytest.mark.parametrize('default', [True, False])
    def test_an_absent_flag_is_the_default(self, default: bool) -> None:
        """None is how an absent key arrives"""
        assert validated_flag(None, default, FLAG_KEY) is default

    @pytest.mark.parametrize('value', [True, False])
    def test_a_boolean_is_kept(self, value: bool) -> None:
        """Whatever the default"""
        assert validated_flag(value, not value, FLAG_KEY) is value

    @pytest.mark.parametrize('value', NOT_BOOLEANS)
    def test_anything_else_is_refused_naming_the_flag_and_type(self, value: Any) -> None:
        """A falsy non-boolean too: 0 and '' are no more a flag than 'false' is"""
        with pytest.raises(ProviderConfigError) as exc_info:
            validated_flag(value, False, FLAG_KEY)

        assert str(exc_info.value) == _not_boolean_message(FLAG_KEY, value)


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

    def test_an_absent_flag_is_the_class_default(self) -> None:
        """The base class's default is active"""
        assert BaseAuthProviderConfig().is_active() is BaseAuthProviderConfig.DEFAULT_CONFIG_VALUES[
            PROVIDER_ACTIVE_KEY]

    @pytest.mark.parametrize('value', NOT_BOOLEANS)
    def test_a_flag_that_is_no_boolean_is_refused(self, value: Any) -> None:
        """is_active() can only ever answer a boolean"""
        with pytest.raises(ProviderConfigError) as exc_info:
            BaseAuthProviderConfig(active=value)

        assert str(exc_info.value) == _not_boolean_message(PROVIDER_ACTIVE_KEY, value)

    def test_an_extra_key_does_not_displace_the_flag(self) -> None:
        """A stored document carrying a stray key must not shadow the one field that is declared."""
        config = BaseAuthProviderConfig(active=True, unexpected='value')

        assert config.is_active() is True
        assert config.unexpected == 'value'


class TestLocalConstruction:
    """A missing `active` reads as the local provider's default, never as a falsy None."""

    def test_a_config_built_from_nothing_is_active(self) -> None:
        """A stored config written without the key is what `PROVIDER_CONFIG_CLASS(**stored)` passes."""
        assert LocalAuthenticationProviderConfig(**{}).is_active() is True

    def test_an_explicit_none_is_the_default_too(self) -> None:
        """`{'active': null}` is the other shape an API client can store."""
        assert LocalAuthenticationProviderConfig(active=None).is_active() is True

    @pytest.mark.parametrize('active', [True, False])
    def test_an_explicit_flag_is_kept(self, active: bool) -> None:
        """Only an absent flag is defaulted; a stored False is still shown as False."""
        assert LocalAuthenticationProviderConfig(active=active).is_active() is active

    def test_the_default_comes_from_the_class_defaults(self) -> None:
        """One source for the default - the value the settings page seeds a new section with."""
        default = LocalAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES[PROVIDER_ACTIVE_KEY]

        assert LocalAuthenticationProviderConfig().is_active() is default

    @pytest.mark.parametrize('value', ['false', 0, 'true'])
    def test_a_flag_that_is_no_boolean_is_refused(self, value: Any) -> None:
        """The local flag is only shown, never read by a login - it is still a boolean or nothing"""
        with pytest.raises(ProviderConfigError):
            LocalAuthenticationProviderConfig(active=value)

    def test_building_a_config_leaves_the_class_defaults_alone(self) -> None:
        """The defaults dict is shared by every section that lacks an entry, so it must not change."""
        before = dict(LocalAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES)
        LocalAuthenticationProviderConfig(active=False)

        assert LocalAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES == before


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


class TestLdapFlags:
    """The provider flag and the group-mapping flag are booleans or absent"""

    @pytest.mark.parametrize('value', NOT_BOOLEANS)
    def test_an_active_flag_that_is_no_boolean_is_refused(self, value: Any) -> None:
        """'false' among them - read by its truthiness it switched the provider on"""
        with pytest.raises(ProviderConfigError) as exc_info:
            LdapAuthenticationProviderConfig(active=value)

        assert str(exc_info.value) == _not_boolean_message(PROVIDER_ACTIVE_KEY, value)

    @pytest.mark.parametrize('value', [True, False])
    def test_a_boolean_active_flag_decides(self, value: bool) -> None:
        """What the login sweep asks"""
        config = LdapAuthenticationProviderConfig(active=value)

        assert LdapAuthenticationProvider.is_active_for(config) is value

    def test_an_absent_active_flag_is_off(self) -> None:
        """LDAP's default"""
        assert LdapAuthenticationProviderConfig().is_active() is False

    @pytest.mark.parametrize('value', NOT_BOOLEANS)
    def test_a_group_mapping_flag_that_is_no_boolean_is_refused(self, value: Any) -> None:
        """'false' switched the group mapping on, moving users between groups"""
        with pytest.raises(ProviderConfigError) as exc_info:
            LdapAuthenticationProviderConfig(groups={LdapGroupsKey.ACTIVE.value: value, 'mapping': []})

        assert str(exc_info.value) == _not_boolean_message(GROUPS_ACTIVE_FLAG, value)

    @pytest.mark.parametrize('groups', [{'mapping': []}, {LdapGroupsKey.ACTIVE.value: None},
                                        {LdapGroupsKey.ACTIVE.value: True}])
    def test_a_group_mapping_flag_that_is_absent_or_boolean_is_kept(self, groups: dict[str, Any]) -> None:
        """The settings are kept as given"""
        assert LdapAuthenticationProviderConfig(groups=groups).groups is groups

    @pytest.mark.parametrize('groups', ['active', [{'active': True}], 5])
    def test_groups_that_are_no_object_are_refused(self, groups: Any) -> None:
        """Their flag cannot be read at all"""
        with pytest.raises(ProviderConfigError) as exc_info:
            LdapAuthenticationProviderConfig(groups=groups)

        assert str(exc_info.value) == GROUPS_NOT_AN_OBJECT_MSG.format(kind=type(groups).__name__)

    @pytest.mark.parametrize('groups', [None, {}, []])
    def test_empty_groups_read_as_the_default(self, groups: Any) -> None:
        """As before: an empty value is no setting"""
        assert LdapAuthenticationProviderConfig(groups=groups).groups == \
            LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES['groups']


class TestLdapDefaultsAreCopies:
    """A config built without a section hands out copies of the class defaults, never the dicts themselves"""

    @pytest.mark.parametrize('key', ['server_config', 'connection_config', 'search', 'groups'])
    def test_each_default_is_an_equal_copy(self, key: str) -> None:
        """Equal, not the same object"""
        config = LdapAuthenticationProviderConfig()
        default = LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES[key]

        assert getattr(config, key) == default
        assert getattr(config, key) is not default

    def test_changing_a_config_leaves_the_class_defaults_alone(self) -> None:
        """A nested change included"""
        before = deepcopy(LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES)
        config = LdapAuthenticationProviderConfig()

        config.server_config['host'] = LDAP_HOST
        config.groups['mapping'].append({'group_dn': GROUP_DN, 'group_id': GROUP_ID})

        assert LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES == before


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
