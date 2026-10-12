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
Unit tests for the CmdbUserGroup usage census (group_usage_helper)

Stub managers answer the four reads, so each part of the census - members, the LDAP settings, the type ACLs and the
sole-grantee rule - its refusal message, its answer shape and the ACL entry removal with its undo are tested without
a database
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.group_usage_helper import (
    GroupUsage,
    abort_if_group_in_use,
    read_group_usage,
    remove_group_from_type_acls,
)
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_IN_USE_MSG,
    GROUP_USE_LDAP_DEFAULT,
    GROUP_USE_LDAP_MAPPING,
    GROUP_USE_SEPARATOR,
    GROUP_USE_SOLE_GRANTEE,
    GroupUsageKey,
)
from cmdb.security.acl.builder import build_group_permissions_path
# -------------------------------------------------------------------------------------------------------------------- #

GROUP: int = 5
OTHER_GROUP: int = 7
DELETED_GROUP: int = 9
MEMBERS: int = 3
SOLE_TYPE: int = 21
SHARED_TYPE: int = 22
OPEN_TYPE: int = 23
GROUP_DN: str = 'cn=admins,dc=example,dc=com'
OTHER_DN: str = 'cn=staff,dc=example,dc=com'
READ: list[str] = ['READ']
TYPES_COLLECTION: str = 'framework.types'
PATH: str = build_group_permissions_path(GROUP)


def _acl(includes: dict[int, Any], activated: bool = True) -> dict[str, Any]:
    """A stored acl block, keyed by group id."""
    return {'activated': activated, 'groups': {'includes': {str(key): value for key, value in includes.items()}}}


def _auth(default_group: Any, mapping: list[tuple[str, Any]] | None = None) -> dict[str, Any]:
    """A stored auth section with one LDAP entry."""
    rows = [{'group_dn': dn, 'group_id': group_id} for dn, group_id in mapping or []]

    return {'providers': [{'class_name': 'LdapAuthenticationProvider',
                           'config': {'default_group': default_group, 'groups': {'mapping': rows}}}]}


def _managers(auth: Any = None, type_documents: list[dict[str, Any]] | None = None,
              existing: set[int] | None = None) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Stub users, settings, types and groups managers."""
    users, settings, types, groups = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    users.count_documents.return_value = MEMBERS
    settings.get_all_values_from_section.return_value = auth or {}
    types.find.return_value = type_documents or []
    types.collection = TYPES_COLLECTION
    groups.find_existing_public_ids.side_effect = lambda ids: set(ids) & (existing or set())

    return users, settings, types, groups


def _type(type_id: int, acl: dict[str, Any]) -> dict[str, Any]:
    """A projected type document."""
    return {'public_id': type_id, 'acl': acl}


class TestReadGroupUsage:
    """read_group_usage"""

    def test_an_unused_group(self) -> None:
        """Members only - nothing blocks"""
        usage = read_group_usage(GROUP, _managers())

        assert usage.to_json() == {
            GroupUsageKey.MEMBERS.value: MEMBERS, GroupUsageKey.LDAP_DEFAULT_GROUP.value: False,
            GroupUsageKey.LDAP_GROUP_MAPPINGS.value: [], GroupUsageKey.SOLE_GRANTEE_TYPE_IDS.value: [],
            GroupUsageKey.ACL_TYPE_IDS.value: [], GroupUsageKey.BLOCKS_DELETE.value: False,
        }

    def test_the_members_are_counted_by_group_id(self) -> None:
        """One count"""
        managers = _managers()

        read_group_usage(GROUP, managers)

        managers[0].count_documents.assert_called_once_with({'group_id': GROUP})

    def test_the_ldap_default_group(self) -> None:
        """Blocks"""
        usage = read_group_usage(GROUP, _managers(auth=_auth(GROUP)))

        assert usage.ldap_default_group and usage.blocks_delete

    def test_the_ldap_mapping_rows_naming_it(self) -> None:
        """Only the rows of this group; a digit string counts"""
        auth = _auth(OTHER_GROUP, [(GROUP_DN, GROUP), (OTHER_DN, OTHER_GROUP), ('cn=x', str(GROUP))])

        usage = read_group_usage(GROUP, _managers(auth=auth))

        assert usage.ldap_group_mappings == [GROUP_DN, 'cn=x']
        assert not usage.ldap_default_group and usage.blocks_delete

    def test_a_type_acl_granting_only_it_is_a_sole_grantee(self) -> None:
        """Blocks - deleting it would lock the type"""
        documents = [_type(SOLE_TYPE, _acl({GROUP: READ, DELETED_GROUP: READ}))]

        usage = read_group_usage(GROUP, _managers(type_documents=documents, existing={GROUP, OTHER_GROUP}))

        assert usage.sole_grantee_type_ids == [SOLE_TYPE]
        assert usage.acl_entries == {SOLE_TYPE: READ}
        assert usage.blocks_delete

    def test_a_shared_or_open_acl_only_names_it(self) -> None:
        """Not blocking - its entry is removed by the delete"""
        documents = [_type(SHARED_TYPE, _acl({GROUP: READ, OTHER_GROUP: READ})),
                     _type(OPEN_TYPE, _acl({GROUP: READ}, activated=False))]

        usage = read_group_usage(GROUP, _managers(type_documents=documents, existing={GROUP, OTHER_GROUP}))

        assert not usage.sole_grantee_type_ids and not usage.blocks_delete
        assert usage.to_json()[GroupUsageKey.ACL_TYPE_IDS.value] == [SHARED_TYPE, OPEN_TYPE]

    def test_the_types_are_read_by_the_groups_acl_path_projected(self) -> None:
        """One read, the ACL only"""
        managers = _managers()

        read_group_usage(GROUP, managers)

        managers[2].find.assert_called_once_with(criteria={PATH: {'$exists': True}},
                                                 projection={'public_id': 1, 'acl': 1})

    def test_without_types_no_group_read(self) -> None:
        """Nothing to judge"""
        managers = _managers()

        read_group_usage(GROUP, managers)

        managers[3].find_existing_public_ids.assert_not_called()

    def test_the_other_granted_groups_are_read_once(self) -> None:
        """One read for every type together, the group itself not asked"""
        documents = [_type(SHARED_TYPE, _acl({GROUP: READ, OTHER_GROUP: READ})),
                     _type(SOLE_TYPE, _acl({GROUP: READ, DELETED_GROUP: READ}))]
        managers = _managers(type_documents=documents, existing={OTHER_GROUP})

        read_group_usage(GROUP, managers)

        managers[3].find_existing_public_ids.assert_called_once_with([OTHER_GROUP, DELETED_GROUP])

    def test_a_missing_auth_section_reads_as_empty(self) -> None:
        """The section is read with an empty default"""
        managers = _managers()

        read_group_usage(GROUP, managers)

        managers[1].get_all_values_from_section.assert_called_once_with('auth', default={})


class TestRefusal:
    """GroupUsage.holders and abort_if_group_in_use"""

    def test_every_holder_is_named_in_order(self) -> None:
        """Default, mappings, then the locked types"""
        usage = GroupUsage(ldap_default_group=True, ldap_group_mappings=[GROUP_DN],
                           sole_grantee_type_ids=[SOLE_TYPE])

        with pytest.raises(HTTPException) as exc_info:
            abort_if_group_in_use(usage, GROUP)

        holders = GROUP_USE_SEPARATOR.join([
            GROUP_USE_LDAP_DEFAULT, GROUP_USE_LDAP_MAPPING.format(group_dns=[GROUP_DN]),
            GROUP_USE_SOLE_GRANTEE.format(type_ids=[SOLE_TYPE]),
        ])
        assert exc_info.value.code == 400
        assert exc_info.value.description == GROUP_IN_USE_MSG.format(public_id=GROUP, holders=holders)

    def test_members_and_shared_acls_do_not_block(self) -> None:
        """The action decides about members; a shared ACL loses the entry"""
        abort_if_group_in_use(GroupUsage(members=MEMBERS, acl_entries={SHARED_TYPE: READ}), GROUP)


class TestRemoveGroupFromTypeAcls:
    """remove_group_from_type_acls"""

    @staticmethod
    def _run(entries: dict[int, Any]) -> tuple[MagicMock, MagicMock]:
        """Runs the removal; answers the stub types manager and ledger."""
        types, ledger = _managers()[2], MagicMock()

        remove_group_from_type_acls(ledger, types, GROUP, GroupUsage(acl_entries=entries))

        return types, ledger

    def test_nothing_to_remove_writes_nothing(self) -> None:
        """No ledger entry either"""
        types, ledger = self._run({})

        types.update_many_raw.assert_not_called()
        ledger.compensated.assert_not_called()

    def test_one_unset_for_every_type_recorded_before_it_runs(self) -> None:
        """The ledger first, then the write"""
        types, ledger = self._run({SHARED_TYPE: READ, OPEN_TYPE: []})

        assert ledger.compensated.call_args.args[0] == TYPES_COLLECTION
        types.update_many_raw.assert_called_once_with(
            {'public_id': {'$in': [SHARED_TYPE, OPEN_TYPE]}}, {'$unset': {PATH: ''}})

    def test_the_undo_writes_each_types_own_entry_back(self) -> None:
        """Not one shared value"""
        types, ledger = self._run({SHARED_TYPE: READ, OPEN_TYPE: []})

        ledger.compensated.call_args.kwargs['undo']()

        assert [call.args for call in types.update.call_args_list] == [
            ({'public_id': SHARED_TYPE}, {'$set': {PATH: READ}}),
            ({'public_id': OPEN_TYPE}, {'$set': {PATH: []}}),
        ]

    @pytest.mark.parametrize('restored, expected', [(2, True), (1, False)], ids=['all', 'one-missing'])
    def test_the_verify_counts_the_restored_entries(self, restored: int, expected: bool) -> None:
        """Every type carries the key again"""
        types, ledger = self._run({SHARED_TYPE: READ, OPEN_TYPE: READ})
        types.count_documents.return_value = restored

        assert ledger.compensated.call_args.kwargs['verify']() is expected
        types.count_documents.assert_called_once_with(
            {'public_id': {'$in': [SHARED_TYPE, OPEN_TYPE]}, PATH: {'$exists': True}})
