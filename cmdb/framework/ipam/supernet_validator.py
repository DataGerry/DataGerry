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
Validator for SUPERNET CmdbObjects

Surfaces canonical-CIDR and address-family-consistency errors. Unlike a SUBNET, a SUPERNET has
no parent reference and no siblings to check against, so validation is stateless (no DB access):
it only inspects the supernet's own network range and its 'dg-supernet-type' selector. Each
check is a small helper to remain unit-testable, mirroring subnet_validator
"""
from typing import Any

from cmdb.models.special_type_model.ipam_constants import IpamValidationDetailKey
from cmdb.utils import BaseStrEnum, build_error
from cmdb.framework.ipam.cidr import Network, network_family, validate_canonical_cidr_value
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR CODES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class SupernetErrorCode(BaseStrEnum):
    """Stable codes for structured supernet validation errors"""
    CIDR_INVALID = 'cidr_invalid'
    TYPE_FAMILY_MISMATCH = 'type_family_mismatch'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                INDIVIDUAL CHECKS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _check_canonical_cidr(network_range: str) -> tuple[Network | None, list[dict[str, Any]]]:
    """
    Validates the candidate CIDR is a strict (canonical) IPv4 or IPv6 CIDR, emitting CIDR_INVALID
    on failure

    Thin domain-specific alias over validate_canonical_cidr_value that binds the error code to
    SupernetErrorCode.CIDR_INVALID

    Args:
        network_range (str): The candidate CIDR

    Returns:
        tuple[Network | None, list[dict[str, Any]]]: (parsed network or None, list of errors)
    """
    return validate_canonical_cidr_value(network_range, SupernetErrorCode.CIDR_INVALID)


def _check_type_matches_family(candidate: Network, supernet_type: str | None) -> list[dict[str, Any]]:
    """
    Validates the SUPERNET's 'dg-supernet-type' selector agrees with the CIDR's actual family

    The check is skipped when no supernet_type is supplied (the pre-validation route may omit it),
    so callers that cannot provide the selector are not forced to. When supplied, an 'ipv4'
    selector on an IPv6 CIDR (or vice versa) emits TYPE_FAMILY_MISMATCH. An unrecognised selector
    value is treated as not matching the candidate's family

    Args:
        candidate (Network): The parsed candidate CIDR
        supernet_type (str | None): The 'dg-supernet-type' value ('ipv4' / 'ipv6'), or None to skip

    Returns:
        list[dict[str, Any]]: A single-element error list on mismatch, empty when consistent
            or when no supernet_type was supplied
    """
    if supernet_type is None:
        return []

    actual_family: str = network_family(candidate)

    if supernet_type == actual_family:
        return []

    return [build_error(
        SupernetErrorCode.TYPE_FAMILY_MISMATCH,
        f"Supernet type '{supernet_type}' does not match the address family '{actual_family}' of {candidate}",
        {
            IpamValidationDetailKey.CANDIDATE: str(candidate),
            IpamValidationDetailKey.SUPERNET_TYPE: supernet_type,
            IpamValidationDetailKey.CIDR_FAMILY: actual_family,
        },
    )]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ORCHESTRATOR                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def validate_supernet(network_range: str, supernet_type: str | None = None) -> list[dict[str, Any]]:
    """
    Validates a candidate SUPERNET CmdbObject's network range and address family

    Returns the accumulated list of errors so the caller can render or abort. An empty list means
    valid. When ``supernet_type`` is supplied it must agree with the CIDR's actual family. There
    is no parent / sibling / containment check - a supernet stands on its own

    Args:
        network_range (str): The candidate IPv4 or IPv6 CIDR (must be canonical, host bits zeroed)
        supernet_type (str | None): The 'dg-supernet-type' selector ('ipv4' / 'ipv6'); when given
            it is cross-checked against the CIDR family. None skips the family-vs-type check

    Returns:
        list[dict[str, Any]]: Structured validation errors; empty when the candidate is valid
    """
    candidate, errors = _check_canonical_cidr(network_range)

    if candidate is None:
        return errors

    errors.extend(_check_type_matches_family(candidate, supernet_type))

    return errors
