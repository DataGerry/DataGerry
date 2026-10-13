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
Unit tests for cmdb.security.auth.providers.ldap_group_references

Where a stored or sent auth settings section names a CmdbUserGroup: each LDAP entry's default group (the provider's
own default when it is missing) and each mapping row, in order; other providers and malformed parts are ignored.
And how a stored group value reads as an id
"""
from typing import Any

import pytest

from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_constants import LDAP_PROVIDER_CLASS_NAME
from cmdb.security.auth.providers.ldap_group_references import (
    LdapGroupReference,
    as_group_id,
    ldap_group_references,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOCAL_PROVIDER: str = 'LocalAuthenticationProvider'
DEFAULT_GROUP: int = 4
MAPPED_GROUP: int = 6
GROUP_DN: str = 'cn=admins,dc=example,dc=com'
OTHER_DN: str = 'cn=staff,dc=example,dc=com'
PROVIDER_DEFAULT: int = LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES['default_group']


def _section(config: Any, class_name: str = LDAP_PROVIDER_CLASS_NAME) -> dict[str, Any]:
    """An auth settings section with the local provider and one more entry."""
    return {'providers': [{'class_name': LOCAL_PROVIDER, 'config': {'default_group': MAPPED_GROUP}},
                          {'class_name': class_name, 'config': config}]}


class TestLdapGroupReferences:
    """ldap_group_references"""

    def test_the_default_group_then_each_mapping_row(self) -> None:
        """In order; the local provider's config is never read"""
        config = {'default_group': DEFAULT_GROUP, 'groups': {'mapping': [
            {'group_dn': GROUP_DN, 'group_id': MAPPED_GROUP}, {'group_dn': OTHER_DN, 'group_id': 'x'},
        ]}}

        assert ldap_group_references(_section(config)) == [
            LdapGroupReference(DEFAULT_GROUP), LdapGroupReference(MAPPED_GROUP, GROUP_DN),
            LdapGroupReference('x', OTHER_DN),
        ]

    @pytest.mark.parametrize('default_group', [None, 0], ids=['null', 'zero'])
    def test_a_missing_default_group_reads_as_the_providers_default(self, default_group: Any) -> None:
        """The way LdapAuthenticationProviderConfig reads it"""
        references = ldap_group_references(_section({'default_group': default_group}))

        assert references == [LdapGroupReference(PROVIDER_DEFAULT)]
        assert references[0].is_default

    def test_a_mapping_row_is_not_the_default(self) -> None:
        """Even one without a DN"""
        reference = ldap_group_references(_section({'groups': {'mapping': [{'group_id': MAPPED_GROUP}]}}))[1]

        assert reference == LdapGroupReference(MAPPED_GROUP, '')
        assert not reference.is_default

    @pytest.mark.parametrize('section', [None, [], {}, {'providers': None}, {'providers': ['x', None]}],
                             ids=['none', 'list', 'empty', 'providers-null', 'entries-not-documents'])
    def test_a_malformed_section_names_nothing(self, section: Any) -> None:
        """Never raises"""
        assert not ldap_group_references(section)

    def test_another_provider_names_nothing(self) -> None:
        """Only the LDAP entries"""
        assert not ldap_group_references({'providers': [{'class_name': LOCAL_PROVIDER, 'config': {}}]})

    @pytest.mark.parametrize('groups', [None, 'x', {'mapping': None}, {'mapping': ['row']}],
                             ids=['none', 'string', 'mapping-null', 'row-not-a-document'])
    def test_a_malformed_groups_block_names_the_default_only(self, groups: Any) -> None:
        """The rows that are no documents are skipped"""
        assert ldap_group_references(_section({'default_group': DEFAULT_GROUP, 'groups': groups})) == [
            LdapGroupReference(DEFAULT_GROUP),
        ]

    def test_a_config_that_is_no_document_still_has_the_default(self) -> None:
        """The provider's own default"""
        assert ldap_group_references(_section('x')) == [LdapGroupReference(PROVIDER_DEFAULT)]


class TestAsGroupId:
    """as_group_id"""

    @pytest.mark.parametrize('value, expected', [(DEFAULT_GROUP, DEFAULT_GROUP), (str(MAPPED_GROUP), MAPPED_GROUP)],
                             ids=['int', 'digit-string'])
    def test_an_id_reads_as_itself(self, value: Any, expected: int) -> None:
        """The provider reads both with int()"""
        assert as_group_id(value) == expected

    @pytest.mark.parametrize('value', [True, False, 0, -1, '0', 'x', '1.5', 2.0, None, [DEFAULT_GROUP]],
                             ids=['true', 'false', 'zero', 'negative', 'zero-string', 'letter', 'decimal-string',
                                  'float', 'none', 'list'])
    def test_anything_else_is_no_id(self, value: Any) -> None:
        """A boolean is no id, though Python counts it an int"""
        assert as_group_id(value) is None
