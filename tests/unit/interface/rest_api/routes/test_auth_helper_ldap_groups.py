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
Unit tests for auth_helper.abort_if_ldap_groups_unusable

The auth-settings write refuses an LDAP default group or mapping row whose value is no group id, then one whose id
no CmdbUserGroup carries - both before anything is stored, with one read of the groups
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.auth_helper import abort_if_ldap_groups_unusable
from cmdb.interface.rest_api.routes.routes_helper import UNKNOWN_REFERENCES_MSG
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import USER_GROUP_LABEL
from cmdb.models.security_models.auth_settings_constants import LDAP_GROUP_NOT_AN_ID_MSG
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_GROUP: int = 4
MAPPED_GROUP: int = 6
MISSING_GROUP: int = 99
GROUP_DN: str = 'cn=admins,dc=example,dc=com'


NO_MAPPING: object = object()


def _section(default_group: Any, mapped: Any = NO_MAPPING) -> dict[str, Any]:
    """An auth section whose LDAP entry names the given groups."""
    mapping = [] if mapped is NO_MAPPING else [{'group_dn': GROUP_DN, 'group_id': mapped}]

    return {'providers': [{'class_name': 'LdapAuthenticationProvider',
                           'config': {'default_group': default_group, 'groups': {'mapping': mapping}}}]}


def _groups(existing: set[int]) -> MagicMock:
    """A stub GroupsManager answering which ids exist."""
    manager = MagicMock()
    manager.find_existing_public_ids.side_effect = lambda ids: set(ids) & existing

    return manager


def _refusal(section: dict[str, Any], groups: MagicMock) -> str:
    """The 400 a refused section raises."""
    with pytest.raises(HTTPException) as exc_info:
        abort_if_ldap_groups_unusable(section, groups)

    assert exc_info.value.code == 400
    return exc_info.value.description


def test_existing_groups_pass_with_one_read() -> None:
    """Default and mapping together"""
    groups = _groups({DEFAULT_GROUP, MAPPED_GROUP})

    abort_if_ldap_groups_unusable(_section(DEFAULT_GROUP, MAPPED_GROUP), groups)

    groups.find_existing_public_ids.assert_called_once_with([DEFAULT_GROUP, MAPPED_GROUP])


@pytest.mark.parametrize('section, missing', [
    (_section(MISSING_GROUP), MISSING_GROUP),
    (_section(DEFAULT_GROUP, MISSING_GROUP), MISSING_GROUP),
], ids=['default', 'mapping'])
def test_a_missing_group_is_refused_by_id(section: dict[str, Any], missing: int) -> None:
    """The shared unknown-reference message"""
    assert _refusal(section, _groups({DEFAULT_GROUP})) == UNKNOWN_REFERENCES_MSG.format(
        entity_label=USER_GROUP_LABEL, unknown=[missing])


@pytest.mark.parametrize('value', ['x', True, -1, None], ids=['letter', 'boolean', 'negative', 'null'])
def test_a_mapping_value_that_is_no_id_is_refused_before_any_read(value: Any) -> None:
    """Named as sent"""
    groups = _groups({DEFAULT_GROUP})

    assert _refusal(_section(DEFAULT_GROUP, value), groups) == LDAP_GROUP_NOT_AN_ID_MSG.format(values=[value])
    groups.find_existing_public_ids.assert_not_called()


def test_a_section_without_an_ldap_entry_reads_nothing() -> None:
    """Nothing to check"""
    groups = _groups(set())

    abort_if_ldap_groups_unusable({'providers': []}, groups)

    groups.find_existing_public_ids.assert_not_called()
