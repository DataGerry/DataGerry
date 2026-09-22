"""
Unit tests for the ACL scoping of the IPAM reads

Until 2026-09-16 every IPAM read was unscoped: a group denied the SUBNET CmdbType through `/objects`
could still read a subnet's whole IP table - owner summaries and stored MACs included - through
`/ipam/subnet/overview/<id>`, and export the same data to CSV. An ACL lives on the CmdbType, so the
scoping is an exclusion of denied `type_id`s.

Three properties are pinned here, and the third is the one that is easy to get wrong:

* a **presentation** read is narrowed to the types the caller may see
* an **invariant** read is NOT - the validators check a candidate against every existing object,
  because an ACL-filtered check would report an overlapping CIDR as valid and the write would then
  accept it (see `workflows/ipam.md`)
* a row whose carrier is denied is **masked, not dropped** - dropping it would show the address as
  free, the user would try to assign it, and the unscoped write-time check would refuse an address
  they cannot see
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.ipam.read_scope import resolve_read_scope
from cmdb.framework.ipam.subnet_overview.assigned_rows import (
    AssignedField,
    load_assigned_rows_map,
)
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObjectKey
# -------------------------------------------------------------------------------------------------------------------- #

SCOPE_PATH: str = 'cmdb.framework.ipam.read_scope'

ALLOWED_TYPE_ID: int = 11
DENIED_TYPE_ID: int = 22


# -------------------------------------------------------------------------------------------------------------------- #
#                                            narrow_criteria_by_denied_types                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestNarrowCriteria:
    """The pure half of the ACL: excluding denied type_ids from a find criteria."""

    def test_nothing_denied_leaves_the_criteria_alone(self) -> None:
        """The common case - most installations activate an ACL on few types or none."""
        criteria = {CmdbObjectKey.PUBLIC_ID.value: 5}

        assert ObjectsManager.narrow_criteria_by_denied_types(criteria, []) is criteria
        assert ObjectsManager.narrow_criteria_by_denied_types(criteria, None) is criteria

    def test_a_denied_type_is_excluded(self) -> None:
        """The exclusion the ACL builder produces."""
        narrowed = ObjectsManager.narrow_criteria_by_denied_types(
            {CmdbObjectKey.PUBLIC_ID.value: 5}, [DENIED_TYPE_ID],
        )

        assert narrowed == {
            '$and': [
                {CmdbObjectKey.PUBLIC_ID.value: 5},
                {CmdbObjectKey.TYPE_ID.value: {'$nin': [DENIED_TYPE_ID]}},
            ],
        }

    def test_it_does_not_overwrite_a_type_id_the_caller_already_filters_on(self) -> None:
        """
        The reason it combines with `$and` instead of merging

        Most IPAM reads filter on `type_id` themselves - "every SUBNET" - and a merge would silently
        replace the caller's filter with the ACL's, returning objects of every other type instead.
        """
        narrowed = ObjectsManager.narrow_criteria_by_denied_types(
            {CmdbObjectKey.TYPE_ID.value: ALLOWED_TYPE_ID}, [DENIED_TYPE_ID],
        )

        assert narrowed['$and'][0] == {CmdbObjectKey.TYPE_ID.value: ALLOWED_TYPE_ID}
        assert narrowed['$and'][1] == {CmdbObjectKey.TYPE_ID.value: {'$nin': [DENIED_TYPE_ID]}}

    def test_the_original_criteria_is_not_mutated(self) -> None:
        """The caller may reuse its own dict."""
        criteria = {CmdbObjectKey.PUBLIC_ID.value: 5}

        ObjectsManager.narrow_criteria_by_denied_types(criteria, [DENIED_TYPE_ID])

        assert criteria == {CmdbObjectKey.PUBLIC_ID.value: 5}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  resolve_read_scope                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveReadScope:
    """Turning a request user into the denied-type list, once per request."""

    def test_no_user_is_an_unscoped_read(self) -> None:
        """What an invariant check passes, and what it must keep meaning."""
        assert resolve_read_scope(None) == []

    def test_a_user_resolves_through_the_acl_builder(self) -> None:
        """The scope is the ACL's own answer, not a second implementation of it."""
        user = MagicMock()

        with patch(f'{SCOPE_PATH}.resolve_denied_type_ids', return_value=[DENIED_TYPE_ID]) as resolver:
            assert resolve_read_scope(user) == [DENIED_TYPE_ID]

        assert resolver.call_args.args[0] is user

    def test_it_asks_for_the_read_permission(self) -> None:
        """A view must not be narrowed by whether the caller could also write."""
        from cmdb.security.acl.permission import AccessControlPermission

        with patch(f'{SCOPE_PATH}.resolve_denied_type_ids', return_value=[]) as resolver:
            resolve_read_scope(MagicMock())

        assert resolver.call_args.args[1] == AccessControlPermission.READ


# -------------------------------------------------------------------------------------------------------------------- #
#                                        masking a denied carrier's assigned row                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _row(object_id: int, type_id: int, ip: str, mac: str) -> dict[str, Any]:
    """One aggregation row, shaped as the pipeline projects it."""
    return {
        AssignedField.OBJECT_ID: object_id,
        AssignedField.TYPE_ID: type_id,
        AssignedField.IP: ip,
        AssignedField.MAC: mac,
    }


@pytest.fixture(name='rows_manager')
def fixture_rows_manager() -> MagicMock:
    """An ObjectsManager whose aggregation yields one visible and one denied row."""
    manager = MagicMock()
    manager.aggregate_objects.return_value = [
        _row(101, ALLOWED_TYPE_ID, '10.0.0.5', 'aa:bb:cc:dd:ee:01'),
        _row(202, DENIED_TYPE_ID, '10.0.0.6', 'aa:bb:cc:dd:ee:02'),
    ]

    return manager


def _network():
    """The /24 both rows sit inside."""
    from ipaddress import ip_network

    return ip_network('10.0.0.0/24')


class TestMaskingDeniedRows:
    """A row the caller may not read keeps its address and loses its identity."""

    def test_unscoped_reads_keep_every_identity(self, rows_manager: MagicMock) -> None:
        """The baseline - no user, nothing denied, nothing hidden."""
        assigned = load_assigned_rows_map(rows_manager, 1, _network())

        assert assigned['10.0.0.6'][AssignedField.OBJECT_ID] == 202
        assert assigned['10.0.0.6'][AssignedField.MAC] == 'aa:bb:cc:dd:ee:02'

    def test_the_denied_row_is_still_present(self, rows_manager: MagicMock) -> None:
        """
        Masked, NOT dropped - the whole point

        Dropping it would report 10.0.0.6 as free; the user would try to assign it and the write-time
        check, which is global and stays unscoped, would refuse an address they cannot see.
        """
        assigned = load_assigned_rows_map(rows_manager, 1, _network(), [DENIED_TYPE_ID])

        assert '10.0.0.6' in assigned

    def test_the_denied_rows_identity_is_withheld(self, rows_manager: MagicMock) -> None:
        """Owner, its type and the MAC are what the caller may not have."""
        assigned = load_assigned_rows_map(rows_manager, 1, _network(), [DENIED_TYPE_ID])
        denied = assigned['10.0.0.6']

        assert denied[AssignedField.OBJECT_ID] is None
        assert denied[AssignedField.TYPE_ID] is None
        assert denied[AssignedField.MAC] is None

    def test_the_allowed_row_is_untouched(self, rows_manager: MagicMock) -> None:
        """Scoping must narrow what is hidden, not what is shown."""
        assigned = load_assigned_rows_map(rows_manager, 1, _network(), [DENIED_TYPE_ID])
        allowed = assigned['10.0.0.5']

        assert allowed[AssignedField.OBJECT_ID] == 101
        assert allowed[AssignedField.MAC] == 'aa:bb:cc:dd:ee:01'

    def test_the_masked_row_keeps_its_validity_flag(self, rows_manager: MagicMock) -> None:
        """The overview still counts it as occupied and in-range."""
        assigned = load_assigned_rows_map(rows_manager, 1, _network(), [DENIED_TYPE_ID])

        assert assigned['10.0.0.6'][AssignedField.IS_VALID] is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the invariant readers stay unscoped                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheValidatorsStayUnscoped:
    """
    The rule that must survive every future "add the ACL here" change

    An overlap check evaluated over a per-user-visible subset would report an overlapping CIDR as
    valid, and the write - which runs the same validator - would accept it. The data would enter an
    invalid state through no fault of the user.
    """

    def test_the_subnet_validator_never_passes_a_user_to_the_manager(self) -> None:
        """Read off the source, so an added `user=` argument fails here."""
        from pathlib import Path

        source = Path('cmdb/framework/ipam/subnet_validator.py').read_text(encoding='utf-8')

        assert 'user=' not in source
        assert 'permission=' not in source
        assert 'narrow_criteria_by_denied_types' not in source

    def test_the_vlan_validator_never_passes_a_user_to_the_manager(self) -> None:
        """Same rule, same reason."""
        from pathlib import Path

        source = Path('cmdb/framework/ipam/vlan_validator.py').read_text(encoding='utf-8')

        assert 'user=' not in source
        assert 'permission=' not in source

    def test_enforcement_never_passes_a_user_to_the_manager(self) -> None:
        """The write-invariant dispatcher's IPAM half enforces the same global rule."""
        from pathlib import Path

        source = Path('cmdb/framework/ipam/enforcement.py').read_text(encoding='utf-8')

        assert 'permission=' not in source
