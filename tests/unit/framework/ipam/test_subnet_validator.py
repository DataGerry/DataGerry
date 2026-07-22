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
Unit tests for cmdb.framework.ipam.subnet_validator

Covers the individual checks (_check_canonical_cidr, _check_in_supernet, _check_sibling_overlap),
the small DB helpers (_load_object_by_id, _find_subnets_by_field — only their filter shapes
since their value lives in real Mongo behavior) and the validate_subnet orchestrator. The
in-module helper resolve_special_type_id is exercised naturally through mocked
types_manager.get_one_by; for the orchestrator both type lookups co-occur, so get_one_by uses a
side_effect that switches on the SpecialType in the filter

IPAM validation errors are bare {message} dicts (no machine-readable code, no details), so the
checks are distinguished by a stable substring of their human-readable message
"""
from typing import Any
from ipaddress import IPv4Network

from unittest.mock import MagicMock

from cmdb.utils import ValidationErrorKey
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    IpAddressFamily,
    SupernetField,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.cidr import parse_cidr
from cmdb.framework.ipam.subnet_validator import (
    _check_canonical_cidr,
    _check_in_supernet,
    _check_sibling_overlap,
    _check_type_matches_family,
    _find_subnets_by_field,
    _load_object_by_id,
    validate_subnet,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
SUPERNET_OBJECT_ID: int = 100
SUBNET_OBJECT_ID: int = 200
SIBLING_SUBNET_ID: int = 300

VALID_PARENT_RANGE: str = '10.0.0.0/16'
VALID_CANDIDATE_RANGE: str = '10.0.0.0/24'
OUT_OF_RANGE_CANDIDATE: str = '192.168.1.0/24'

VALID_PARENT_RANGE_V6: str = '2001:db8::/32'
VALID_CANDIDATE_RANGE_V6: str = '2001:db8:1::/48'

# Stable message fragments each check emits (errors carry only a 'message')
MSG_CIDR_INVALID: str = 'is not a canonical IPv4/IPv6 CIDR'
MSG_TYPE_REQUIRED: str = "Subnet type ('dg-subnet-type') is required"
MSG_FAMILY_MISMATCH: str = 'does not match the address family'
MSG_NO_SUPERNET_TYPE: str = 'No SUPERNET CmdbType is defined'
MSG_SUPERNET_NOT_FOUND: str = 'does not exist'
MSG_SUPERNET_BROKEN: str = 'has no valid'
MSG_NOT_CONTAINED: str = 'is not contained in supernet'
MSG_SIBLING_OVERLAP: str = 'overlaps with sibling subnet'


def _msg(error: dict[str, Any]) -> str:
    """Returns an error's human-readable message."""
    return error[ValidationErrorKey.MESSAGE]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_object_doc(
    public_id: int,
    type_id: int,
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with the given fields list."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.FIELDS: fields or [],
    }


def _make_supernet_doc(public_id: int, network_range: Any) -> dict[str, Any]:
    """Builds a SUPERNET CmdbObject doc with a network-range field entry."""
    return _make_object_doc(
        public_id=public_id,
        type_id=SUPERNET_TYPE_ID,
        fields=[{
            CmdbObjectFieldKey.NAME: SupernetField.NETWORK_RANGE,
            CmdbObjectFieldKey.VALUE: network_range,
        }],
    )


def _make_subnet_doc(public_id: int, network_range: Any) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc with a network-range field entry (sibling fixture)."""
    return _make_object_doc(
        public_id=public_id,
        type_id=SUBNET_TYPE_ID,
        fields=[{
            CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE,
            CmdbObjectFieldKey.VALUE: network_range,
        }],
    )


def _make_special_type_router(mapping: dict[SpecialType, int | None]) -> Any:
    """Returns a side_effect callable that dispatches get_one_by results by SpecialType filter."""
    def router(filter_doc: dict[str, Any]) -> dict[str, Any] | None:
        type_id = mapping.get(filter_doc[TypeSchemaKey.SPECIAL_TYPE])
        return {CmdbObjectKey.PUBLIC_ID: type_id} if type_id is not None else None

    return router


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _check_canonical_cidr                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_canonical_cidr_returns_network_and_no_errors_for_canonical_input() -> None:
    """A canonical CIDR yields the parsed network and an empty error list"""
    network, errors = _check_canonical_cidr(VALID_CANDIDATE_RANGE)

    assert network is not None
    assert str(network) == VALID_CANDIDATE_RANGE
    assert not errors


def test_check_canonical_cidr_reports_cidr_invalid_for_garbage_input() -> None:
    """A non-CIDR string yields None and a CIDR-invalid error naming the raw value"""
    network, errors = _check_canonical_cidr('not-a-cidr')

    assert network is None
    assert len(errors) == 1
    assert MSG_CIDR_INVALID in _msg(errors[0])
    assert 'not-a-cidr' in _msg(errors[0])


def test_check_canonical_cidr_rejects_non_canonical_cidr_with_host_bits_set() -> None:
    """'10.0.0.5/24' has host bits set and must be rejected as non-canonical"""
    network, errors = _check_canonical_cidr('10.0.0.5/24')

    assert network is None
    assert len(errors) == 1
    assert MSG_CIDR_INVALID in _msg(errors[0])


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _check_type_matches_family                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_type_matches_family_reports_missing_selector_for_the_subnet_field() -> None:
    """The SUBNET binding rejects a None selector, naming the dg-subnet-type field

    The full required-selector / mismatch matrix is covered once on the shared
    ``validate_family_selector`` core in test_cidr; here only the SUBNET binding is pinned
    """
    errors = _check_type_matches_family(parse_cidr(VALID_CANDIDATE_RANGE), None)

    assert len(errors) == 1
    assert MSG_TYPE_REQUIRED in _msg(errors[0])


def test_check_type_matches_family_reports_mismatch() -> None:
    """The SUBNET binding rejects a selector that disagrees with the CIDR family"""
    errors = _check_type_matches_family(parse_cidr(VALID_CANDIDATE_RANGE_V6), IpAddressFamily.IPV4)

    assert len(errors) == 1
    assert MSG_FAMILY_MISMATCH in _msg(errors[0])


def test_check_type_matches_family_returns_empty_when_selector_matches() -> None:
    """A consistent selector passes the SUBNET binding without errors"""
    assert not _check_type_matches_family(parse_cidr(VALID_CANDIDATE_RANGE), IpAddressFamily.IPV4)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _load_object_by_id                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_object_by_id_returns_none_when_manager_returns_no_match() -> None:
    """An empty find_objects result yields None"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    assert _load_object_by_id(objects_manager, SUPERNET_OBJECT_ID) is None


def test_load_object_by_id_returns_first_match_when_manager_has_results() -> None:
    """Only the first doc is returned (PUBLIC_ID is unique by DB invariant)"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_object_doc(SUPERNET_OBJECT_ID, SUPERNET_TYPE_ID)]

    result = _load_object_by_id(objects_manager, SUPERNET_OBJECT_ID)

    assert result is not None
    assert result[CmdbObjectKey.PUBLIC_ID] == SUPERNET_OBJECT_ID


def test_load_object_by_id_queries_with_public_id_filter_and_as_dict() -> None:
    """The query filter pins to PUBLIC_ID only, with as_dict=True"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    _load_object_by_id(objects_manager, SUPERNET_OBJECT_ID)

    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID: SUPERNET_OBJECT_ID},
        as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _find_subnets_by_field                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_subnets_by_field_returns_raw_docs_from_manager() -> None:
    """Full subnet docs are returned without projection (overlap check needs the fields array)"""
    siblings = [_make_subnet_doc(SIBLING_SUBNET_ID, '10.0.1.0/24')]
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = siblings

    result = _find_subnets_by_field(
        objects_manager, SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET, SUPERNET_OBJECT_ID,
    )

    assert result is siblings


def test_find_subnets_by_field_builds_type_scoped_elem_match_filter() -> None:
    """Filter pins TYPE_ID plus FIELDS $elemMatch on the given (name, value) pair"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    _find_subnets_by_field(
        objects_manager, SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET, SUPERNET_OBJECT_ID,
    )

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
            CmdbObjectKey.FIELDS: {
                '$elemMatch': {
                    CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET,
                    CmdbObjectFieldKey.VALUE: SUPERNET_OBJECT_ID,
                },
            },
        },
        as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                               _check_in_supernet                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _candidate_network() -> Any:
    """Returns the parsed IPv4Network used as 'candidate' in containment tests."""
    return IPv4Network(VALID_CANDIDATE_RANGE)


def test_check_in_supernet_reports_type_missing_when_no_supernet_cmdbtype_defined() -> None:
    """No SUPERNET CmdbType → 'no SUPERNET CmdbType' error; no object lookup performed"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert MSG_NO_SUPERNET_TYPE in _msg(errors[0])
    objects_manager.find_objects.assert_not_called()


def test_check_in_supernet_reports_not_found_when_supernet_object_missing() -> None:
    """find_objects returns empty → 'does not exist' naming the queried id"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert MSG_SUPERNET_NOT_FOUND in _msg(errors[0])
    assert str(SUPERNET_OBJECT_ID) in _msg(errors[0])


def test_check_in_supernet_reports_not_found_when_object_has_wrong_type_id() -> None:
    """An object exists at that id but is not a SUPERNET type → 'does not exist'"""
    wrong_type_doc = _make_object_doc(SUPERNET_OBJECT_ID, type_id=SUPERNET_TYPE_ID + 1)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [wrong_type_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert MSG_SUPERNET_NOT_FOUND in _msg(errors[0])


def test_check_in_supernet_reports_broken_state_when_supernet_range_unparseable() -> None:
    """A supernet whose stored range is not canonical CIDR → broken-state error"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, 'not-a-cidr')]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert MSG_SUPERNET_BROKEN in _msg(errors[0])


def test_check_in_supernet_reports_broken_state_when_supernet_range_is_non_string() -> None:
    """A supernet whose stored range is not a string at all → broken-state error"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, 42)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert MSG_SUPERNET_BROKEN in _msg(errors[0])


def test_check_in_supernet_reports_not_in_supernet_when_candidate_outside_range() -> None:
    """A candidate that doesn't fit inside the parent supernet → 'not contained' naming both ranges"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(
        objects_manager, types_manager, IPv4Network(OUT_OF_RANGE_CANDIDATE), SUPERNET_OBJECT_ID,
    )

    assert len(errors) == 1
    message = _msg(errors[0])
    assert MSG_NOT_CONTAINED in message
    assert OUT_OF_RANGE_CANDIDATE in message
    assert VALID_PARENT_RANGE in message


def test_check_in_supernet_returns_no_errors_when_candidate_fits_supernet() -> None:
    """A candidate that fits inside the parent supernet yields no errors"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert not errors


def test_check_in_supernet_returns_no_errors_when_ipv6_candidate_fits_ipv6_supernet() -> None:
    """An IPv6 candidate strictly inside an IPv6 supernet yields no errors"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE_V6)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(
        objects_manager, types_manager, parse_cidr(VALID_CANDIDATE_RANGE_V6), SUPERNET_OBJECT_ID,
    )

    assert not errors


def test_check_in_supernet_reports_family_mismatch_for_ipv6_candidate_under_ipv4_supernet() -> None:
    """An IPv6 candidate under an IPv4 supernet → family mismatch (not 'not contained')"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(
        objects_manager, types_manager, parse_cidr(VALID_CANDIDATE_RANGE_V6), SUPERNET_OBJECT_ID,
    )

    assert len(errors) == 1
    message = _msg(errors[0])
    assert MSG_FAMILY_MISMATCH in message
    assert VALID_CANDIDATE_RANGE_V6 in message
    assert VALID_PARENT_RANGE in message
    # The family tokens render as the bare 'ipv4' / 'ipv6' values, not the enum repr
    assert IpAddressFamily.IPV6 in message
    assert IpAddressFamily.IPV4 in message
    assert 'IpAddressFamily' not in message


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _check_sibling_overlap                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_sibling_overlap_returns_empty_when_subnet_cmdbtype_not_defined() -> None:
    """No SUBNET type → no siblings can exist → empty (also no objects query)"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    errors = _check_sibling_overlap(
        objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID, exclude_subnet_id=None,
    )

    assert not errors
    objects_manager.find_objects.assert_not_called()


def test_check_sibling_overlap_returns_empty_when_no_siblings_under_parent() -> None:
    """SUBNET type exists but no siblings reference the parent → empty"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    errors = _check_sibling_overlap(
        objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID, exclude_subnet_id=None,
    )

    assert not errors


def test_check_sibling_overlap_skips_excluded_subnet_id() -> None:
    """The candidate's own pre-edit doc must not be flagged as an overlap against itself"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_subnet_doc(SIBLING_SUBNET_ID, VALID_CANDIDATE_RANGE)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    errors = _check_sibling_overlap(
        objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID,
        exclude_subnet_id=SIBLING_SUBNET_ID,
    )

    assert not errors


def test_check_sibling_overlap_skips_sibling_with_unparseable_range() -> None:
    """A sibling whose stored range is unparseable cannot be compared and is silently skipped"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_subnet_doc(SIBLING_SUBNET_ID, 'not-a-cidr')]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    errors = _check_sibling_overlap(
        objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID, exclude_subnet_id=None,
    )

    assert not errors


def test_check_sibling_overlap_reports_overlap_with_one_sibling() -> None:
    """A sibling whose range overlaps the candidate yields one overlap error naming both ranges"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_subnet_doc(SIBLING_SUBNET_ID, '10.0.0.128/25')]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    errors = _check_sibling_overlap(
        objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID, exclude_subnet_id=None,
    )

    assert len(errors) == 1
    message = _msg(errors[0])
    assert MSG_SIBLING_OVERLAP in message
    assert VALID_CANDIDATE_RANGE in message
    assert '10.0.0.128/25' in message


def test_check_sibling_overlap_reports_only_overlapping_siblings_in_mixed_input() -> None:
    """Among multiple siblings, only those that actually overlap produce errors"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_subnet_doc(SIBLING_SUBNET_ID, '10.0.1.0/24'),
        _make_subnet_doc(SIBLING_SUBNET_ID + 1, '10.0.0.128/25'),
        _make_subnet_doc(SIBLING_SUBNET_ID + 2, '10.0.2.0/24'),
    ]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    errors = _check_sibling_overlap(
        objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID, exclude_subnet_id=None,
    )

    assert len(errors) == 1
    assert '10.0.0.128/25' in _msg(errors[0])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                validate_subnet                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_subnet_returns_only_cidr_error_for_invalid_cidr() -> None:
    """An invalid CIDR short-circuits; no DB lookups happen, no other checks run"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    errors = validate_subnet(objects_manager, types_manager, 'not-a-cidr', parent_supernet_id=SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert MSG_CIDR_INVALID in _msg(errors[0])
    objects_manager.find_objects.assert_not_called()
    types_manager.get_one_by.assert_not_called()


def test_validate_subnet_skips_parent_checks_when_no_parent_supernet_id_provided() -> None:
    """Standalone candidate (no parent_supernet_id) → only CIDR check, no supernet/overlap"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    errors = validate_subnet(
        objects_manager, types_manager, VALID_CANDIDATE_RANGE, subnet_type=IpAddressFamily.IPV4,
    )

    assert not errors
    objects_manager.find_objects.assert_not_called()
    types_manager.get_one_by.assert_not_called()


def test_validate_subnet_returns_empty_when_valid_cidr_and_supernet_and_no_siblings() -> None:
    """Happy path: candidate fits supernet and has no overlapping siblings"""
    objects_manager = MagicMock()
    objects_manager.find_objects.side_effect = [
        [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE)],
        [],
    ]
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _make_special_type_router({
        SpecialType.SUPERNET: SUPERNET_TYPE_ID,
        SpecialType.SUBNET: SUBNET_TYPE_ID,
    })

    errors = validate_subnet(
        objects_manager, types_manager, VALID_CANDIDATE_RANGE,
        parent_supernet_id=SUPERNET_OBJECT_ID, subnet_type=IpAddressFamily.IPV4,
    )

    assert not errors


def test_validate_subnet_accumulates_supernet_and_overlap_errors() -> None:
    """The orchestrator does not short-circuit: both supernet and overlap errors are returned"""
    objects_manager = MagicMock()
    objects_manager.find_objects.side_effect = [
        [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE)],
        [_make_subnet_doc(SIBLING_SUBNET_ID, '192.168.1.0/25')],
    ]
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _make_special_type_router({
        SpecialType.SUPERNET: SUPERNET_TYPE_ID,
        SpecialType.SUBNET: SUBNET_TYPE_ID,
    })

    errors = validate_subnet(
        objects_manager, types_manager, OUT_OF_RANGE_CANDIDATE, parent_supernet_id=SUPERNET_OBJECT_ID,
    )

    messages = ' '.join(_msg(e) for e in errors)
    assert MSG_NOT_CONTAINED in messages
    assert MSG_SIBLING_OVERLAP in messages


def test_validate_subnet_excludes_self_id_from_sibling_overlap_during_edit() -> None:
    """When editing a subnet, its own id is passed as exclude_subnet_id and is not flagged"""
    objects_manager = MagicMock()
    objects_manager.find_objects.side_effect = [
        [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE)],
        [_make_subnet_doc(SUBNET_OBJECT_ID, VALID_CANDIDATE_RANGE)],
    ]
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _make_special_type_router({
        SpecialType.SUPERNET: SUPERNET_TYPE_ID,
        SpecialType.SUBNET: SUBNET_TYPE_ID,
    })

    errors = validate_subnet(
        objects_manager, types_manager, VALID_CANDIDATE_RANGE,
        parent_supernet_id=SUPERNET_OBJECT_ID, exclude_subnet_id=SUBNET_OBJECT_ID,
        subnet_type=IpAddressFamily.IPV4,
    )

    assert not errors


def test_validate_subnet_reports_type_family_mismatch_without_touching_db() -> None:
    """A subnet_type that disagrees with the CIDR family is flagged before any parent lookup"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    errors = validate_subnet(
        objects_manager, types_manager, VALID_CANDIDATE_RANGE_V6, subnet_type=IpAddressFamily.IPV4,
    )

    assert len(errors) == 1
    assert MSG_FAMILY_MISMATCH in _msg(errors[0])
    objects_manager.find_objects.assert_not_called()


def test_validate_subnet_passes_for_consistent_ipv6_candidate_in_ipv6_supernet() -> None:
    """Happy path: IPv6 CIDR, matching 'ipv6' selector, inside an IPv6 supernet, no siblings"""
    objects_manager = MagicMock()
    objects_manager.find_objects.side_effect = [
        [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE_V6)],
        [],
    ]
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _make_special_type_router({
        SpecialType.SUPERNET: SUPERNET_TYPE_ID,
        SpecialType.SUBNET: SUBNET_TYPE_ID,
    })

    errors = validate_subnet(
        objects_manager, types_manager, VALID_CANDIDATE_RANGE_V6,
        parent_supernet_id=SUPERNET_OBJECT_ID, subnet_type=IpAddressFamily.IPV6,
    )

    assert not errors
