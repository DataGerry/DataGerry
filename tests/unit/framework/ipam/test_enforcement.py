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
Unit tests for cmdb.framework.ipam.enforcement

Covers the pure helpers, the per-SpecialType enforcers, the delete guards and the two
orchestrators. Downstream validators (validate_subnet, validate_vlan, validate_interface_rows,
the reference finders) are patched at the enforcement module path so each enforcer test
verifies the dispatch/glue logic in isolation. The validators themselves have their own
dedicated unit-test files. _build_delete_guard_error is intentionally not tested directly:
it is a one-line wrapper around build_error, covered by its callers
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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
    SupernetField,
    VlanField,
    InterfaceField,
    IpamSection,
    IpamValidationDetailKey,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.subnet_validator import SubnetErrorCode
from cmdb.framework.ipam.enforcement import (
    DeleteGuardErrorCode,
    _coerce_int,
    _enforce_interface_rows,
    _enforce_subnet_object,
    _enforce_supernet_object,
    _enforce_vlan_object,
    _extract_interface_rows,
    _format_id_list,
    _guard_subnet_delete,
    _guard_supernet_delete,
    _resolve_object_special_type,
    enforce_delete_guards,
    enforce_object_invariants,
    format_errors_for_abort,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
VLAN_TYPE_ID: int = 12
OTHER_TYPE_ID: int = 99
CANDIDATE_OBJECT_ID: int = 500
PARENT_SUPERNET_ID: int = 600
SIBLING_SUBNET_ID: int = 700

PREV_RANGE: str = '10.0.0.0/24'
NEW_RANGE: str = '10.0.0.0/16'
INVALID_CIDR: str = 'not-a-cidr'

ENF_PATH: str = 'cmdb.framework.ipam.enforcement'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_object_doc(
    public_id: int | None,
    type_id: int | None,
    fields: list[dict[str, Any]] | None = None,
    mds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with optional fields and MDS sections."""
    doc: dict[str, Any] = {}

    if public_id is not None:
        doc[CmdbObjectKey.PUBLIC_ID] = public_id

    if type_id is not None:
        doc[CmdbObjectKey.TYPE_ID] = type_id

    if fields is not None:
        doc[CmdbObjectKey.FIELDS] = fields

    if mds is not None:
        doc[CmdbObjectKey.MULTI_DATA_SECTIONS] = mds

    return doc


def _make_field(name: Any, value: Any) -> dict[str, Any]:
    """Builds one entry for an object 'fields' list."""
    return {CmdbObjectFieldKey.NAME: name, CmdbObjectFieldKey.VALUE: value}


def _make_interface_row(subnet_id: int | None, ip: str | None) -> dict[str, Any]:
    """Builds one MDS interface row."""
    data: list[dict[str, Any]] = []

    if subnet_id is not None:
        data.append(_make_field(InterfaceField.SUBNET, subnet_id))

    if ip is not None:
        data.append(_make_field(InterfaceField.IP, ip))

    return {CmdbObjectMdsRowKey.DATA: data}


def _make_interface_section(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds an MDS section entry of the dg-ipam-interface template kind."""
    return {
        CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
        CmdbObjectMdsKey.VALUES: rows,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              format_errors_for_abort                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_format_errors_for_abort_returns_prefix_only_for_empty_list() -> None:
    """No errors → only the 'IPAM validation failed: ' prefix is emitted"""
    assert format_errors_for_abort([]) == 'IPAM validation failed: '


def test_format_errors_for_abort_uses_message_when_present() -> None:
    """A single error with a message yields the message after the prefix"""
    errors = [{ValidationErrorKey.MESSAGE: 'IP not in subnet', ValidationErrorKey.CODE: 'ip_not_in_subnet'}]

    assert format_errors_for_abort(errors) == 'IPAM validation failed: IP not in subnet'


def test_format_errors_for_abort_falls_back_to_code_when_message_missing() -> None:
    """Without a message the error's code is used as the human-readable text"""
    errors = [{ValidationErrorKey.CODE: 'ip_reserved'}]

    assert format_errors_for_abort(errors) == 'IPAM validation failed: ip_reserved'


def test_format_errors_for_abort_falls_back_to_unknown_when_both_missing() -> None:
    """An error dict with neither message nor code shows up as 'unknown error'"""
    assert format_errors_for_abort([{}]) == 'IPAM validation failed: unknown error'


def test_format_errors_for_abort_joins_multiple_errors_with_pipe_separator() -> None:
    """Two or more errors are joined with ' | ' between their messages"""
    errors = [
        {ValidationErrorKey.MESSAGE: 'first'},
        {ValidationErrorKey.MESSAGE: 'second'},
    ]

    assert format_errors_for_abort(errors) == 'IPAM validation failed: first | second'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _resolve_object_special_type                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_object_special_type_returns_none_when_get_type_returns_none() -> None:
    """No matching CmdbType for the id → None"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = None

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) is None


def test_resolve_object_special_type_returns_none_when_get_type_returns_empty_dict() -> None:
    """An empty type doc is treated as 'no type'"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {}

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) is None


def test_resolve_object_special_type_returns_none_when_type_has_no_special_type_field() -> None:
    """A type doc that doesn't carry a special_type yields None"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {TypeSchemaKey.SPECIAL_TYPE: None}

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) is None


def test_resolve_object_special_type_returns_none_for_unrecognized_special_type_value() -> None:
    """A special_type string that doesn't match any SpecialType member is treated as None"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {TypeSchemaKey.SPECIAL_TYPE: 'NOT_A_SPECIAL_TYPE'}

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) is None


@pytest.mark.parametrize('raw_value, expected', [
    ('SUBNET', SpecialType.SUBNET),
    ('SUPERNET', SpecialType.SUPERNET),
    ('VLAN', SpecialType.VLAN),
])
def test_resolve_object_special_type_returns_enum_for_valid_value(raw_value: str, expected: SpecialType) -> None:
    """A recognized SpecialType value is returned as the corresponding enum member"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {TypeSchemaKey.SPECIAL_TYPE: raw_value}

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   _coerce_int                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value', [None, '', 0])
def test_coerce_int_returns_none_for_empty_or_zero_sentinel(value: Any) -> None:
    """None, empty string and literal 0 are treated as 'absent' and yield None"""
    assert _coerce_int(value) is None


@pytest.mark.parametrize('value, expected', [
    (42, 42),
    ('42', 42),
    (-5, -5),
])
def test_coerce_int_converts_valid_int_or_int_string(value: Any, expected: int) -> None:
    """Numeric ints and int-formatted strings are coerced to int"""
    assert _coerce_int(value) == expected


@pytest.mark.parametrize('value', ['abc', '12.5', [], {}, object()])
def test_coerce_int_returns_none_for_unconvertible_input(value: Any) -> None:
    """A value that int() cannot parse yields None instead of raising"""
    assert _coerce_int(value) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _extract_interface_rows                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_extract_interface_rows_returns_empty_when_no_mds_sections() -> None:
    """An object with no multi_data_sections list yields no rows"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    assert _extract_interface_rows(obj) == []


def test_extract_interface_rows_skips_non_interface_sections() -> None:
    """Sections whose section_id is not the interface template are ignored"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        {
            CmdbObjectMdsKey.SECTION_ID: IpamSection.INFORMATION,
            CmdbObjectMdsKey.VALUES: [_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5')],
        },
    ])

    assert _extract_interface_rows(obj) == []


def test_extract_interface_rows_returns_subnet_and_ip_for_complete_row() -> None:
    """A complete row yields a (index, subnet_ref, ip) tuple"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5')]),
    ])

    assert _extract_interface_rows(obj) == [(0, SIBLING_SUBNET_ID, '10.0.0.5')]


def test_extract_interface_rows_yields_none_pair_for_empty_row() -> None:
    """A row with empty data still emits a tuple — with both slots None — preserving its index"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([{CmdbObjectMdsRowKey.DATA: []}]),
    ])

    assert _extract_interface_rows(obj) == [(0, None, None)]


def test_extract_interface_rows_treats_empty_string_ip_as_none() -> None:
    """An IP value that is an empty string is normalized to None (interface IP is optional)"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '')]),
    ])

    assert _extract_interface_rows(obj) == [(0, SIBLING_SUBNET_ID, None)]


def test_extract_interface_rows_preserves_row_indices_in_order() -> None:
    """Row indices reflect the position inside the section's values list"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([
            _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.1'),
            _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.2'),
            _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.3'),
        ]),
    ])

    indices = [row[0] for row in _extract_interface_rows(obj)]
    assert indices == [0, 1, 2]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  _format_id_list                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_format_id_list_returns_empty_string_for_no_refs() -> None:
    """No references → empty string"""
    assert _format_id_list([]) == ''


def test_format_id_list_returns_single_id_without_separator() -> None:
    """One reference → just its id, no comma"""
    assert _format_id_list([{CmdbObjectKey.PUBLIC_ID: 7}]) == '7'


def test_format_id_list_joins_multiple_ids_with_comma_separator() -> None:
    """Multiple references → comma-separated id string in the input order"""
    refs = [
        {CmdbObjectKey.PUBLIC_ID: 7},
        {CmdbObjectKey.PUBLIC_ID: 9},
        {CmdbObjectKey.PUBLIC_ID: 11},
    ]

    assert _format_id_list(refs) == '7, 9, 11'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _enforce_subnet_object                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_subnet_candidate(public_id: int | None, network_range: str, parent_id: int | None = None) -> dict[str, Any]:
    """Builds a SUBNET candidate CmdbObject doc."""
    fields = [_make_field(SubnetField.NETWORK_RANGE, network_range)]

    if parent_id is not None:
        fields.append(_make_field(SubnetField.PARENT_SUPERNET, parent_id))

    return _make_object_doc(public_id=public_id, type_id=SUBNET_TYPE_ID, fields=fields)


def test_enforce_subnet_object_on_insert_runs_validate_subnet() -> None:
    """No previous_object → validate_subnet drives the result and exclude_subnet_id is None"""
    candidate = _make_subnet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, parent_id=PARENT_SUPERNET_ID)

    with patch(f'{ENF_PATH}.validate_subnet', return_value=[]) as validate_mock:
        errors = _enforce_subnet_object(MagicMock(), MagicMock(), candidate, previous_object=None)

    assert errors == []
    validate_mock.assert_called_once()
    assert validate_mock.call_args.kwargs['exclude_subnet_id'] is None


def test_enforce_subnet_object_on_update_passes_candidate_id_as_exclude() -> None:
    """previous_object set → exclude_subnet_id is forwarded so candidate doesn't collide with itself"""
    candidate = _make_subnet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, parent_id=PARENT_SUPERNET_ID)
    previous = _make_subnet_candidate(CANDIDATE_OBJECT_ID, PREV_RANGE, parent_id=PARENT_SUPERNET_ID)

    with patch(f'{ENF_PATH}.validate_subnet', return_value=[]) as validate_mock:
        _enforce_subnet_object(MagicMock(), MagicMock(), candidate, previous_object=previous)

    assert validate_mock.call_args.kwargs['exclude_subnet_id'] == CANDIDATE_OBJECT_ID


def test_enforce_subnet_object_allows_range_change_even_when_interface_ips_would_orphan() -> None:
    """
    Range change to a smaller / disjoint CIDR is permitted: validate_subnet decides on its own,
    no separate guard blocks the save. Interface IPs that no longer fit surface as
    is_valid=False in the subnet IP-Übersicht instead
    """
    candidate = _make_subnet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, parent_id=PARENT_SUPERNET_ID)
    previous = _make_subnet_candidate(CANDIDATE_OBJECT_ID, PREV_RANGE, parent_id=PARENT_SUPERNET_ID)

    with patch(f'{ENF_PATH}.validate_subnet', return_value=[]) as validate_mock:
        errors = _enforce_subnet_object(MagicMock(), MagicMock(), candidate, previous_object=previous)

    assert errors == []
    validate_mock.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _enforce_supernet_object                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_supernet_candidate(public_id: int | None, network_range: Any) -> dict[str, Any]:
    """Builds a SUPERNET candidate CmdbObject doc."""
    return _make_object_doc(
        public_id=public_id,
        type_id=SUPERNET_TYPE_ID,
        fields=[_make_field(SupernetField.NETWORK_RANGE, network_range)],
    )


def test_enforce_supernet_object_emits_cidr_invalid_for_unparseable_range() -> None:
    """An invalid CIDR string on the candidate yields a CIDR_INVALID error"""
    candidate = _make_supernet_candidate(CANDIDATE_OBJECT_ID, INVALID_CIDR)

    errors = _enforce_supernet_object(candidate)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.CIDR_INVALID


def test_enforce_supernet_object_returns_empty_for_canonical_cidr() -> None:
    """A canonical CIDR passes; SUPERNET enforcement is now CIDR-canonicity only"""
    candidate = _make_supernet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE)

    assert _enforce_supernet_object(candidate) == []


def test_enforce_supernet_object_allows_range_change_even_when_child_subnets_would_orphan() -> None:
    """
    Range change is permitted regardless of whether existing child subnets would now fall
    outside the new range: those children surface as is_valid=False in the supernet overview
    so the user can repair or detach them after the fact, instead of the save being blocked
    """
    candidate = _make_supernet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE)

    assert _enforce_supernet_object(candidate) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _enforce_vlan_object                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_enforce_vlan_object_returns_empty_when_no_subnet_ref_present() -> None:
    """A VLAN candidate without a subnet reference does not invoke validate_vlan"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, VLAN_TYPE_ID, fields=[])

    with patch(f'{ENF_PATH}.validate_vlan') as validate_mock:
        errors = _enforce_vlan_object(MagicMock(), MagicMock(), candidate)

    assert errors == []
    validate_mock.assert_not_called()


def test_enforce_vlan_object_delegates_to_validate_vlan_with_subnet_id() -> None:
    """A VLAN candidate with a subnet_ref invokes validate_vlan with the coerced id"""
    candidate = _make_object_doc(
        CANDIDATE_OBJECT_ID, VLAN_TYPE_ID,
        fields=[_make_field(VlanField.SUBNET_REF, '700')],
    )
    expected_error = {ValidationErrorKey.CODE: 'subnet_not_found'}

    with patch(f'{ENF_PATH}.validate_vlan', return_value=[expected_error]) as validate_mock:
        errors = _enforce_vlan_object(MagicMock(), MagicMock(), candidate)

    assert errors == [expected_error]
    validate_mock.assert_called_once()
    assert validate_mock.call_args.args[2] == 700


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _enforce_interface_rows                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_enforce_interface_rows_returns_empty_when_no_rows_present() -> None:
    """An object with no interface rows does not invoke validate_interface_rows"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    with patch(f'{ENF_PATH}.validate_interface_rows') as validate_mock:
        errors = _enforce_interface_rows(MagicMock(), MagicMock(), candidate, previous_object=None)

    assert errors == []
    validate_mock.assert_not_called()


def test_enforce_interface_rows_on_insert_passes_none_as_exclude_object_id() -> None:
    """On insert (no previous_object) the exclude_object_id is None"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5')]),
    ])

    with patch(f'{ENF_PATH}.validate_interface_rows', return_value=[]) as validate_mock:
        _enforce_interface_rows(MagicMock(), MagicMock(), candidate, previous_object=None)

    assert validate_mock.call_args.args[3] is None


def test_enforce_interface_rows_on_update_passes_candidate_id_as_exclude_object_id() -> None:
    """On update the candidate's own public_id is passed as exclude_object_id"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5')]),
    ])
    previous = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    with patch(f'{ENF_PATH}.validate_interface_rows', return_value=[]) as validate_mock:
        _enforce_interface_rows(MagicMock(), MagicMock(), candidate, previous_object=previous)

    assert validate_mock.call_args.args[3] == CANDIDATE_OBJECT_ID


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _guard_supernet_delete                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_guard_supernet_delete_returns_empty_when_no_subnets_reference_it() -> None:
    """No referencing subnets → empty guard error list"""
    with patch(f'{ENF_PATH}.find_subnets_referencing_supernet', return_value=[]):
        errors = _guard_supernet_delete(MagicMock(), MagicMock(), PARENT_SUPERNET_ID)

    assert errors == []


def test_guard_supernet_delete_returns_guard_error_when_subnets_reference_it() -> None:
    """Referencing subnets → single SUPERNET_HAS_REFERENCING_SUBNETS error with the refs in details"""
    refs = [{CmdbObjectKey.PUBLIC_ID: 7, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID}]

    with patch(f'{ENF_PATH}.find_subnets_referencing_supernet', return_value=refs):
        errors = _guard_supernet_delete(MagicMock(), MagicMock(), PARENT_SUPERNET_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == DeleteGuardErrorCode.SUPERNET_HAS_REFERENCING_SUBNETS
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.REFERENCES] == refs


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _guard_subnet_delete                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_guard_subnet_delete_returns_empty_when_no_references_exist() -> None:
    """No vlans and no interface rows reference the subnet → empty"""
    with patch(f'{ENF_PATH}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{ENF_PATH}.find_interfaces_referencing_subnet', return_value=[]):
        errors = _guard_subnet_delete(MagicMock(), MagicMock(), SIBLING_SUBNET_ID)

    assert errors == []


def test_guard_subnet_delete_returns_only_vlan_error_when_only_vlans_reference_it() -> None:
    """Vlans referencing the subnet produce a single VLAN guard error"""
    vlan_refs = [{CmdbObjectKey.PUBLIC_ID: 8, CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID}]

    with patch(f'{ENF_PATH}.find_vlans_referencing_subnet', return_value=vlan_refs), \
         patch(f'{ENF_PATH}.find_interfaces_referencing_subnet', return_value=[]):
        errors = _guard_subnet_delete(MagicMock(), MagicMock(), SIBLING_SUBNET_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == DeleteGuardErrorCode.SUBNET_HAS_REFERENCING_VLANS


def test_guard_subnet_delete_returns_only_interface_error_when_only_interfaces_reference_it() -> None:
    """Interface rows referencing the subnet produce a single INTERFACES guard error"""
    interface_refs = [{CmdbObjectKey.PUBLIC_ID: 9, CmdbObjectKey.TYPE_ID: OTHER_TYPE_ID}]

    with patch(f'{ENF_PATH}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{ENF_PATH}.find_interfaces_referencing_subnet', return_value=interface_refs):
        errors = _guard_subnet_delete(MagicMock(), MagicMock(), SIBLING_SUBNET_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == DeleteGuardErrorCode.SUBNET_HAS_REFERENCING_INTERFACES


def test_guard_subnet_delete_returns_both_errors_when_both_kinds_of_reference_exist() -> None:
    """Both kinds of references produce two guard errors (one per kind)"""
    vlan_refs = [{CmdbObjectKey.PUBLIC_ID: 8, CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID}]
    interface_refs = [{CmdbObjectKey.PUBLIC_ID: 9, CmdbObjectKey.TYPE_ID: OTHER_TYPE_ID}]

    with patch(f'{ENF_PATH}.find_vlans_referencing_subnet', return_value=vlan_refs), \
         patch(f'{ENF_PATH}.find_interfaces_referencing_subnet', return_value=interface_refs):
        errors = _guard_subnet_delete(MagicMock(), MagicMock(), SIBLING_SUBNET_ID)

    codes = {e[ValidationErrorKey.CODE] for e in errors}
    assert codes == {
        DeleteGuardErrorCode.SUBNET_HAS_REFERENCING_VLANS,
        DeleteGuardErrorCode.SUBNET_HAS_REFERENCING_INTERFACES,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                          enforce_object_invariants                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_enforce_object_invariants_returns_empty_when_type_id_is_not_int() -> None:
    """A candidate without an int type_id short-circuits with no errors"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, type_id=None)

    errors = enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    assert errors == []


def test_enforce_object_invariants_dispatches_to_supernet_enforcer() -> None:
    """A SUPERNET-typed candidate routes to _enforce_supernet_object plus interface rows"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, SUPERNET_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUPERNET), \
         patch(f'{ENF_PATH}._enforce_supernet_object', return_value=[]) as supernet_mock, \
         patch(f'{ENF_PATH}._enforce_subnet_object') as subnet_mock, \
         patch(f'{ENF_PATH}._enforce_vlan_object') as vlan_mock, \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[]) as interface_mock:
        enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    supernet_mock.assert_called_once()
    interface_mock.assert_called_once()
    subnet_mock.assert_not_called()
    vlan_mock.assert_not_called()


def test_enforce_object_invariants_dispatches_to_subnet_enforcer() -> None:
    """A SUBNET-typed candidate routes to _enforce_subnet_object plus interface rows"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, SUBNET_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUBNET), \
         patch(f'{ENF_PATH}._enforce_supernet_object') as supernet_mock, \
         patch(f'{ENF_PATH}._enforce_subnet_object', return_value=[]) as subnet_mock, \
         patch(f'{ENF_PATH}._enforce_vlan_object') as vlan_mock, \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[]):
        enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    subnet_mock.assert_called_once()
    supernet_mock.assert_not_called()
    vlan_mock.assert_not_called()


def test_enforce_object_invariants_dispatches_to_vlan_enforcer() -> None:
    """A VLAN-typed candidate routes to _enforce_vlan_object plus interface rows"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, VLAN_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.VLAN), \
         patch(f'{ENF_PATH}._enforce_supernet_object') as supernet_mock, \
         patch(f'{ENF_PATH}._enforce_subnet_object') as subnet_mock, \
         patch(f'{ENF_PATH}._enforce_vlan_object', return_value=[]) as vlan_mock, \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[]):
        enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    vlan_mock.assert_called_once()
    supernet_mock.assert_not_called()
    subnet_mock.assert_not_called()


def test_enforce_object_invariants_runs_interface_rows_for_non_special_type() -> None:
    """A non-IPAM-SpecialType object still runs the interface-row check (rows are global)"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=None), \
         patch(f'{ENF_PATH}._enforce_supernet_object') as supernet_mock, \
         patch(f'{ENF_PATH}._enforce_subnet_object') as subnet_mock, \
         patch(f'{ENF_PATH}._enforce_vlan_object') as vlan_mock, \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[]) as interface_mock:
        enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    interface_mock.assert_called_once()
    supernet_mock.assert_not_called()
    subnet_mock.assert_not_called()
    vlan_mock.assert_not_called()


def test_enforce_object_invariants_accumulates_errors_from_both_layers() -> None:
    """Errors from the per-SpecialType enforcer and the interface-row enforcer are combined"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, SUBNET_TYPE_ID)
    subnet_err = {ValidationErrorKey.CODE: 'subnet_err'}
    interface_err = {ValidationErrorKey.CODE: 'interface_err'}

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUBNET), \
         patch(f'{ENF_PATH}._enforce_subnet_object', return_value=[subnet_err]), \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[interface_err]):
        errors = enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    codes = {e[ValidationErrorKey.CODE] for e in errors}
    assert codes == {'subnet_err', 'interface_err'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                           enforce_delete_guards                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_enforce_delete_guards_returns_empty_for_invalid_type_id() -> None:
    """A target object without an int type_id short-circuits with no errors"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, type_id=None)

    errors = enforce_delete_guards(MagicMock(), MagicMock(), target)

    assert errors == []


def test_enforce_delete_guards_returns_empty_for_invalid_object_id() -> None:
    """A target object without an int public_id short-circuits with no errors"""
    target = _make_object_doc(public_id=None, type_id=SUPERNET_TYPE_ID)

    errors = enforce_delete_guards(MagicMock(), MagicMock(), target)

    assert errors == []


def test_enforce_delete_guards_dispatches_to_supernet_guard_for_supernet_target() -> None:
    """A SUPERNET target routes to _guard_supernet_delete"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, SUPERNET_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUPERNET), \
         patch(f'{ENF_PATH}._guard_supernet_delete', return_value=[]) as supernet_mock, \
         patch(f'{ENF_PATH}._guard_subnet_delete') as subnet_mock:
        enforce_delete_guards(MagicMock(), MagicMock(), target)

    supernet_mock.assert_called_once()
    subnet_mock.assert_not_called()


def test_enforce_delete_guards_dispatches_to_subnet_guard_for_subnet_target() -> None:
    """A SUBNET target routes to _guard_subnet_delete"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, SUBNET_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUBNET), \
         patch(f'{ENF_PATH}._guard_supernet_delete') as supernet_mock, \
         patch(f'{ENF_PATH}._guard_subnet_delete', return_value=[]) as subnet_mock:
        enforce_delete_guards(MagicMock(), MagicMock(), target)

    subnet_mock.assert_called_once()
    supernet_mock.assert_not_called()


def test_enforce_delete_guards_returns_empty_for_vlan_target() -> None:
    """VLAN objects have no IPAM references pointing at them, so delete is unconditionally allowed"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, VLAN_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.VLAN), \
         patch(f'{ENF_PATH}._guard_supernet_delete') as supernet_mock, \
         patch(f'{ENF_PATH}._guard_subnet_delete') as subnet_mock:
        errors = enforce_delete_guards(MagicMock(), MagicMock(), target)

    assert errors == []
    supernet_mock.assert_not_called()
    subnet_mock.assert_not_called()


def test_enforce_delete_guards_returns_empty_for_non_special_type_target() -> None:
    """A non-IPAM SpecialType object passes through unaffected"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=None), \
         patch(f'{ENF_PATH}._guard_supernet_delete') as supernet_mock, \
         patch(f'{ENF_PATH}._guard_subnet_delete') as subnet_mock:
        errors = enforce_delete_guards(MagicMock(), MagicMock(), target)

    assert errors == []
    supernet_mock.assert_not_called()
    subnet_mock.assert_not_called()
