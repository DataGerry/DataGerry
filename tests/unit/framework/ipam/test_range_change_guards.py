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
Unit tests for cmdb.framework.ipam.range_change_guards

Covers the pure helpers (_extract_interface_subnet_and_ip, _check_subnet_children_fit,
_check_interface_ips_fit) and the two orchestrators (check_supernet_range_change,
check_subnet_range_change). The DB enumeration helpers (_find_child_subnets_of_supernet,
_find_objects_with_interface_to_subnet) and the trivial range_changed equality wrapper are
deferred or skipped per agreed scope. Fixture documents reference CmdbObjectKey /
CmdbObjectFieldKey / CmdbObjectMdsKey / CmdbObjectMdsRowKey / SubnetField / InterfaceField /
IpamSection enums for structural keys, per the no-magic-values rule
"""
from ipaddress import IPv4Network
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.utils import ValidationErrorKey
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    InterfaceField,
    IpamSection,
    IpamValidationDetailKey,
)
from cmdb.framework.ipam.range_change_guards import (
    RangeChangeErrorCode,
    _check_interface_ips_fit,
    _check_subnet_children_fit,
    _extract_interface_subnet_and_ip,
    check_subnet_range_change,
    check_supernet_range_change,
)
# -------------------------------------------------------------------------------------------------------------------- #


PARENT_SUPERNET_ID: int = 100
SUBNET_OBJECT_ID: int = 200
SUBNET_TYPE_ID: int = 11

NEW_SUPERNET_RANGE_STR: str = '10.0.0.0/16'
NEW_SUBNET_RANGE_STR: str = '10.0.0.0/24'

RESOLVE_PATH: str = 'cmdb.framework.ipam.range_change_guards.resolve_special_type_id'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_subnet_doc(public_id: int, network_range: Any) -> dict[str, Any]:
    """Builds a minimal SUBNET CmdbObject doc with one network-range field entry."""
    fields: list[dict[str, Any]] = []

    if network_range is not None:
        fields.append({
            CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE,
            CmdbObjectFieldKey.VALUE: network_range,
        })

    return {CmdbObjectKey.PUBLIC_ID: public_id, CmdbObjectKey.FIELDS: fields}


def _make_interface_row(subnet_id: int | None, ip: str | None) -> dict[str, Any]:
    """Builds one MDS row matching the interface section template's row shape."""
    data: list[dict[str, Any]] = []

    if subnet_id is not None:
        data.append(
            {CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: subnet_id},
        )

    if ip is not None:
        data.append(
            {CmdbObjectFieldKey.NAME: InterfaceField.IP, CmdbObjectFieldKey.VALUE: ip},
        )

    return {CmdbObjectMdsRowKey.DATA: data}


def _make_object_with_interface_rows(public_id: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with one dg-ipam-interface MDS section."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.MULTI_DATA_SECTIONS: [
            {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                CmdbObjectMdsKey.VALUES: rows,
            },
        ],
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                       _extract_interface_subnet_and_ip                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_extract_interface_subnet_and_ip_returns_both_when_present() -> None:
    """A complete row yields both the subnet ref and the IP value"""
    row = _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.0.5')

    assert _extract_interface_subnet_and_ip(row) == (SUBNET_OBJECT_ID, '10.0.0.5')


def test_extract_interface_subnet_and_ip_returns_none_for_missing_ip() -> None:
    """A row with only the subnet ref returns None for the IP slot"""
    row = _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip=None)

    assert _extract_interface_subnet_and_ip(row) == (SUBNET_OBJECT_ID, None)


def test_extract_interface_subnet_and_ip_returns_none_for_missing_subnet() -> None:
    """A row with only the IP returns None for the subnet slot"""
    row = _make_interface_row(subnet_id=None, ip='10.0.0.5')

    assert _extract_interface_subnet_and_ip(row) == (None, '10.0.0.5')


def test_extract_interface_subnet_and_ip_returns_none_pair_for_empty_data() -> None:
    """A row with empty data returns (None, None)"""
    empty_row = {CmdbObjectMdsRowKey.DATA: []}

    assert _extract_interface_subnet_and_ip(empty_row) == (None, None)


def test_extract_interface_subnet_and_ip_returns_none_pair_when_data_key_missing() -> None:
    """A row missing the 'data' key is treated as empty rather than raising"""
    assert _extract_interface_subnet_and_ip({}) == (None, None)


def test_extract_interface_subnet_and_ip_ignores_unrelated_field_entries() -> None:
    """Extra fields like MAC don't affect extraction of the (subnet, IP) pair"""
    row = {
        CmdbObjectMdsRowKey.DATA: [
            {CmdbObjectFieldKey.NAME: InterfaceField.MAC, CmdbObjectFieldKey.VALUE: 'aa:bb:cc:dd:ee:ff'},
            {CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: SUBNET_OBJECT_ID},
            {CmdbObjectFieldKey.NAME: InterfaceField.IP, CmdbObjectFieldKey.VALUE: '10.0.0.5'},
        ],
    }

    assert _extract_interface_subnet_and_ip(row) == (SUBNET_OBJECT_ID, '10.0.0.5')


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _check_subnet_children_fit                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_subnet_children_fit_returns_empty_for_no_children() -> None:
    """No children means no errors"""
    errors = _check_subnet_children_fit([], IPv4Network('10.0.0.0/16'), PARENT_SUPERNET_ID)

    assert errors == []


def test_check_subnet_children_fit_passes_child_fully_contained_in_new_range() -> None:
    """A child whose network is a strict subnet of the new range produces no error"""
    children = [_make_subnet_doc(public_id=1, network_range='10.0.1.0/24')]

    errors = _check_subnet_children_fit(children, IPv4Network('10.0.0.0/16'), PARENT_SUPERNET_ID)

    assert errors == []


def test_check_subnet_children_fit_flags_child_not_contained_in_new_range() -> None:
    """A child whose network falls outside the new range produces a CHILD_SUBNET_OUT_OF_RANGE error"""
    children = [_make_subnet_doc(public_id=1, network_range='192.168.1.0/24')]

    errors = _check_subnet_children_fit(children, IPv4Network('10.0.0.0/16'), PARENT_SUPERNET_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == RangeChangeErrorCode.CHILD_SUBNET_OUT_OF_RANGE
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.PARENT_OBJECT_ID] == PARENT_SUPERNET_ID
    assert details[IpamValidationDetailKey.CHILD_SUBNET_ID] == 1
    assert details[IpamValidationDetailKey.CHILD_RANGE] == '192.168.1.0/24'
    assert details[IpamValidationDetailKey.NEW_RANGE] == '10.0.0.0/16'


def test_check_subnet_children_fit_skips_child_with_unparseable_range_string() -> None:
    """A child whose stored range can't be parsed as CIDR is silently skipped (no error)"""
    children = [_make_subnet_doc(public_id=1, network_range='not-a-cidr')]

    errors = _check_subnet_children_fit(children, IPv4Network('10.0.0.0/16'), PARENT_SUPERNET_ID)

    assert errors == []


def test_check_subnet_children_fit_skips_child_with_non_string_range_value() -> None:
    """A child whose range value is not a string is silently skipped (no error)"""
    children = [_make_subnet_doc(public_id=1, network_range=42)]

    errors = _check_subnet_children_fit(children, IPv4Network('10.0.0.0/16'), PARENT_SUPERNET_ID)

    assert errors == []


def test_check_subnet_children_fit_reports_only_offending_children_in_mixed_input() -> None:
    """Among multiple children, only those outside the new range are reported"""
    children = [
        _make_subnet_doc(public_id=1, network_range='10.0.1.0/24'),
        _make_subnet_doc(public_id=2, network_range='192.168.1.0/24'),
        _make_subnet_doc(public_id=3, network_range='10.0.2.0/24'),
        _make_subnet_doc(public_id=4, network_range='172.16.0.0/24'),
    ]

    errors = _check_subnet_children_fit(children, IPv4Network('10.0.0.0/16'), PARENT_SUPERNET_ID)

    reported_ids = {e[ValidationErrorKey.DETAILS][IpamValidationDetailKey.CHILD_SUBNET_ID] for e in errors}
    assert reported_ids == {2, 4}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _check_interface_ips_fit                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_interface_ips_fit_returns_empty_for_no_objects() -> None:
    """No objects to inspect means no errors"""
    errors = _check_interface_ips_fit([], IPv4Network('10.0.0.0/24'), SUBNET_OBJECT_ID)

    assert errors == []


def test_check_interface_ips_fit_passes_ip_inside_new_range() -> None:
    """An interface IP that still falls inside the new range produces no error"""
    objects = [_make_object_with_interface_rows(
        public_id=7,
        rows=[_make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.0.5')],
    )]

    errors = _check_interface_ips_fit(objects, IPv4Network('10.0.0.0/24'), SUBNET_OBJECT_ID)

    assert errors == []


def test_check_interface_ips_fit_flags_ip_outside_new_range() -> None:
    """An interface IP outside the new range produces a CHILD_INTERFACE_IP_OUT_OF_RANGE error"""
    objects = [_make_object_with_interface_rows(
        public_id=7,
        rows=[_make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.1.5')],
    )]

    errors = _check_interface_ips_fit(objects, IPv4Network('10.0.0.0/24'), SUBNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == RangeChangeErrorCode.CHILD_INTERFACE_IP_OUT_OF_RANGE
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.SUBNET_OBJECT_ID] == SUBNET_OBJECT_ID
    assert details[IpamValidationDetailKey.OBJECT_ID] == 7
    assert details[IpamValidationDetailKey.ROW_INDEX] == 0
    assert details[IpamValidationDetailKey.IP_ADDRESS] == '10.0.1.5'
    assert details[IpamValidationDetailKey.NEW_RANGE] == '10.0.0.0/24'


def test_check_interface_ips_fit_skips_rows_referencing_a_different_subnet() -> None:
    """Rows whose subnet ref is not the one being changed are not considered"""
    other_subnet_id = SUBNET_OBJECT_ID + 1
    objects = [_make_object_with_interface_rows(
        public_id=7,
        rows=[_make_interface_row(subnet_id=other_subnet_id, ip='10.0.1.5')],
    )]

    errors = _check_interface_ips_fit(objects, IPv4Network('10.0.0.0/24'), SUBNET_OBJECT_ID)

    assert errors == []


def test_check_interface_ips_fit_skips_unparseable_ip_string() -> None:
    """An IP value that can't be parsed is silently skipped (no error)"""
    objects = [_make_object_with_interface_rows(
        public_id=7,
        rows=[_make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='not-an-ip')],
    )]

    errors = _check_interface_ips_fit(objects, IPv4Network('10.0.0.0/24'), SUBNET_OBJECT_ID)

    assert errors == []


def test_check_interface_ips_fit_skips_non_string_ip_value() -> None:
    """An IP value that isn't a string (e.g. None) is silently skipped (no error)"""
    objects = [_make_object_with_interface_rows(
        public_id=7,
        rows=[_make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip=None)],
    )]

    errors = _check_interface_ips_fit(objects, IPv4Network('10.0.0.0/24'), SUBNET_OBJECT_ID)

    assert errors == []


def test_check_interface_ips_fit_ignores_non_interface_sections() -> None:
    """MDS sections whose section_id is not the interface template are skipped"""
    objects = [{
        CmdbObjectKey.PUBLIC_ID: 7,
        CmdbObjectKey.MULTI_DATA_SECTIONS: [
            {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INFORMATION,
                CmdbObjectMdsKey.VALUES: [
                    _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.1.5'),
                ],
            },
        ],
    }]

    errors = _check_interface_ips_fit(objects, IPv4Network('10.0.0.0/24'), SUBNET_OBJECT_ID)

    assert errors == []


def test_check_interface_ips_fit_reports_each_offending_row_with_its_index() -> None:
    """Multiple offending rows on the same object are reported with distinct row indices"""
    objects = [_make_object_with_interface_rows(
        public_id=7,
        rows=[
            _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.0.5'),
            _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.1.5'),
            _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.2.5'),
        ],
    )]

    errors = _check_interface_ips_fit(objects, IPv4Network('10.0.0.0/24'), SUBNET_OBJECT_ID)

    reported_indices = {e[ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] for e in errors}
    assert reported_indices == {1, 2}


# -------------------------------------------------------------------------------------------------------------------- #
#                                         check_supernet_range_change                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_supernet_range_change_returns_empty_for_non_string_new_value() -> None:
    """A non-string new_range_value short-circuits with an empty result (no validation)"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    errors = check_supernet_range_change(objects_manager, types_manager, PARENT_SUPERNET_ID, 42)

    assert errors == []
    objects_manager.find_objects.assert_not_called()


def test_check_supernet_range_change_returns_empty_for_unparseable_cidr_value() -> None:
    """An unparseable CIDR string short-circuits with an empty result (no validation)"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    errors = check_supernet_range_change(objects_manager, types_manager, PARENT_SUPERNET_ID, 'not-a-cidr')

    assert errors == []
    objects_manager.find_objects.assert_not_called()


def test_check_supernet_range_change_returns_empty_when_subnet_type_not_defined() -> None:
    """When no SUBNET CmdbType exists the guard cannot enumerate children and yields no errors"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(RESOLVE_PATH, return_value=None):
        errors = check_supernet_range_change(
            objects_manager, types_manager, PARENT_SUPERNET_ID, NEW_SUPERNET_RANGE_STR,
        )

    assert errors == []
    objects_manager.find_objects.assert_not_called()


def test_check_supernet_range_change_returns_empty_when_all_children_still_fit() -> None:
    """A valid new range that still contains all child subnets produces no errors"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_subnet_doc(public_id=1, network_range='10.0.1.0/24'),
        _make_subnet_doc(public_id=2, network_range='10.0.2.0/24'),
    ]
    types_manager = MagicMock()

    with patch(RESOLVE_PATH, return_value=SUBNET_TYPE_ID):
        errors = check_supernet_range_change(
            objects_manager, types_manager, PARENT_SUPERNET_ID, NEW_SUPERNET_RANGE_STR,
        )

    assert errors == []


def test_check_supernet_range_change_flags_each_child_that_no_longer_fits() -> None:
    """A new range that excludes some children produces one error per excluded child"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_subnet_doc(public_id=1, network_range='10.0.1.0/24'),
        _make_subnet_doc(public_id=2, network_range='192.168.1.0/24'),
    ]
    types_manager = MagicMock()

    with patch(RESOLVE_PATH, return_value=SUBNET_TYPE_ID):
        errors = check_supernet_range_change(
            objects_manager, types_manager, PARENT_SUPERNET_ID, NEW_SUPERNET_RANGE_STR,
        )

    assert len(errors) == 1
    details = errors[0][ValidationErrorKey.DETAILS]
    assert errors[0][ValidationErrorKey.CODE] == RangeChangeErrorCode.CHILD_SUBNET_OUT_OF_RANGE
    assert details[IpamValidationDetailKey.CHILD_SUBNET_ID] == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                          check_subnet_range_change                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_subnet_range_change_returns_empty_for_non_string_new_value() -> None:
    """A non-string new_range_value short-circuits with an empty result (no validation)"""
    objects_manager = MagicMock()

    errors = check_subnet_range_change(objects_manager, SUBNET_OBJECT_ID, 42)

    assert errors == []
    objects_manager.find_objects.assert_not_called()


def test_check_subnet_range_change_returns_empty_for_unparseable_cidr_value() -> None:
    """An unparseable CIDR string short-circuits with an empty result (no validation)"""
    objects_manager = MagicMock()

    errors = check_subnet_range_change(objects_manager, SUBNET_OBJECT_ID, 'not-a-cidr')

    assert errors == []
    objects_manager.find_objects.assert_not_called()


def test_check_subnet_range_change_returns_empty_when_all_ips_still_fit() -> None:
    """A valid new range that still contains all referenced interface IPs produces no errors"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_object_with_interface_rows(
        public_id=7,
        rows=[
            _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.0.5'),
            _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.0.99'),
        ],
    )]

    errors = check_subnet_range_change(objects_manager, SUBNET_OBJECT_ID, NEW_SUBNET_RANGE_STR)

    assert errors == []


def test_check_subnet_range_change_flags_each_ip_that_no_longer_fits() -> None:
    """A new range that excludes some referenced IPs produces one error per offending row"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_object_with_interface_rows(
        public_id=7,
        rows=[
            _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.0.5'),
            _make_interface_row(subnet_id=SUBNET_OBJECT_ID, ip='10.0.1.5'),
        ],
    )]

    errors = check_subnet_range_change(objects_manager, SUBNET_OBJECT_ID, NEW_SUBNET_RANGE_STR)

    assert len(errors) == 1
    details = errors[0][ValidationErrorKey.DETAILS]
    assert errors[0][ValidationErrorKey.CODE] == RangeChangeErrorCode.CHILD_INTERFACE_IP_OUT_OF_RANGE
    assert details[IpamValidationDetailKey.ROW_INDEX] == 1
    assert details[IpamValidationDetailKey.IP_ADDRESS] == '10.0.1.5'
