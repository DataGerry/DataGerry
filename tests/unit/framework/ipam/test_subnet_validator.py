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
"""
from typing import Any

from unittest.mock import MagicMock

from cmdb.utils import ValidationErrorKey
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    SupernetField,
    IpamValidationDetailKey,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.subnet_validator import (
    SubnetErrorCode,
    _check_canonical_cidr,
    _check_in_supernet,
    _check_sibling_overlap,
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
    assert errors == []


def test_check_canonical_cidr_reports_cidr_invalid_for_garbage_input() -> None:
    """A non-CIDR string yields None and a CIDR_INVALID error carrying the raw value"""
    network, errors = _check_canonical_cidr('not-a-cidr')

    assert network is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.CIDR_INVALID
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.NETWORK_RANGE] == 'not-a-cidr'


def test_check_canonical_cidr_rejects_non_canonical_cidr_with_host_bits_set() -> None:
    """'10.0.0.5/24' has host bits set and must be rejected with CIDR_INVALID"""
    network, errors = _check_canonical_cidr('10.0.0.5/24')

    assert network is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.CIDR_INVALID


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
    from ipaddress import IPv4Network
    return IPv4Network(VALID_CANDIDATE_RANGE)


def test_check_in_supernet_reports_type_missing_when_no_supernet_cmdbtype_defined() -> None:
    """No SUPERNET CmdbType → PARENT_SUPERNET_TYPE_MISSING; no object lookup performed"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.PARENT_SUPERNET_TYPE_MISSING
    objects_manager.find_objects.assert_not_called()


def test_check_in_supernet_reports_not_found_when_supernet_object_missing() -> None:
    """find_objects returns empty → PARENT_SUPERNET_NOT_FOUND with the queried id in details"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.PARENT_SUPERNET_NOT_FOUND
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.SUPERNET_OBJECT_ID] == SUPERNET_OBJECT_ID


def test_check_in_supernet_reports_not_found_when_object_has_wrong_type_id() -> None:
    """An object exists at that id but is not a SUPERNET type → PARENT_SUPERNET_NOT_FOUND"""
    wrong_type_doc = _make_object_doc(SUPERNET_OBJECT_ID, type_id=SUPERNET_TYPE_ID + 1)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [wrong_type_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.PARENT_SUPERNET_NOT_FOUND


def test_check_in_supernet_reports_broken_state_when_supernet_range_unparseable() -> None:
    """A supernet whose stored range is not canonical CIDR → PARENT_SUPERNET_BROKEN_STATE"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, 'not-a-cidr')]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.PARENT_SUPERNET_BROKEN_STATE
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.STORED_VALUE] == 'not-a-cidr'


def test_check_in_supernet_reports_broken_state_when_supernet_range_is_non_string() -> None:
    """A supernet whose stored range is not a string at all → PARENT_SUPERNET_BROKEN_STATE"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, 42)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.PARENT_SUPERNET_BROKEN_STATE


def test_check_in_supernet_reports_not_in_supernet_when_candidate_outside_range() -> None:
    """A candidate that doesn't fit inside the parent supernet → NOT_IN_PARENT_SUPERNET"""
    from ipaddress import IPv4Network

    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(
        objects_manager, types_manager, IPv4Network(OUT_OF_RANGE_CANDIDATE), SUPERNET_OBJECT_ID,
    )

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.NOT_IN_PARENT_SUPERNET
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.CANDIDATE] == OUT_OF_RANGE_CANDIDATE
    assert details[IpamValidationDetailKey.SUPERNET_RANGE] == VALID_PARENT_RANGE


def test_check_in_supernet_returns_no_errors_when_candidate_fits_supernet() -> None:
    """A candidate that fits inside the parent supernet yields no errors"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_supernet_doc(SUPERNET_OBJECT_ID, VALID_PARENT_RANGE)]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    errors = _check_in_supernet(objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID)

    assert errors == []


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

    assert errors == []
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

    assert errors == []


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

    assert errors == []


def test_check_sibling_overlap_skips_sibling_with_unparseable_range() -> None:
    """A sibling whose stored range is unparseable cannot be compared and is silently skipped"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_subnet_doc(SIBLING_SUBNET_ID, 'not-a-cidr')]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    errors = _check_sibling_overlap(
        objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID, exclude_subnet_id=None,
    )

    assert errors == []


def test_check_sibling_overlap_reports_overlap_with_one_sibling() -> None:
    """A sibling whose range overlaps the candidate yields one SIBLING_OVERLAP error"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_make_subnet_doc(SIBLING_SUBNET_ID, '10.0.0.128/25')]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    errors = _check_sibling_overlap(
        objects_manager, types_manager, _candidate_network(), SUPERNET_OBJECT_ID, exclude_subnet_id=None,
    )

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.SIBLING_OVERLAP
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.SIBLING_SUBNET_ID] == SIBLING_SUBNET_ID
    assert details[IpamValidationDetailKey.SIBLING_RANGE] == '10.0.0.128/25'
    assert details[IpamValidationDetailKey.CANDIDATE] == VALID_CANDIDATE_RANGE


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

    reported_ids = {e[ValidationErrorKey.DETAILS][IpamValidationDetailKey.SIBLING_SUBNET_ID] for e in errors}
    assert reported_ids == {SIBLING_SUBNET_ID + 1}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                validate_subnet                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_subnet_returns_only_cidr_error_for_invalid_cidr() -> None:
    """An invalid CIDR short-circuits; no DB lookups happen, no other checks run"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    errors = validate_subnet(objects_manager, types_manager, 'not-a-cidr', parent_supernet_id=SUPERNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SubnetErrorCode.CIDR_INVALID
    objects_manager.find_objects.assert_not_called()
    types_manager.get_one_by.assert_not_called()


def test_validate_subnet_skips_parent_checks_when_no_parent_supernet_id_provided() -> None:
    """Standalone candidate (no parent_supernet_id) → only CIDR check, no supernet/overlap"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    errors = validate_subnet(objects_manager, types_manager, VALID_CANDIDATE_RANGE)

    assert errors == []
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
        objects_manager, types_manager, VALID_CANDIDATE_RANGE, parent_supernet_id=SUPERNET_OBJECT_ID,
    )

    assert errors == []


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

    codes = {e[ValidationErrorKey.CODE] for e in errors}
    assert SubnetErrorCode.NOT_IN_PARENT_SUPERNET in codes
    assert SubnetErrorCode.SIBLING_OVERLAP in codes


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
    )

    assert errors == []
