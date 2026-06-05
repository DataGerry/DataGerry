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

from cmdb.models.special_type_model.ipam_constants import SupernetField, IpamValidationDetailKey
from cmdb.utils import BaseStrEnum
from cmdb.framework.ipam.cidr import Network, validate_canonical_cidr_value, validate_family_selector
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR CODES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class SupernetErrorCode(BaseStrEnum):
    """Stable codes for structured supernet validation errors"""
    CIDR_INVALID = 'cidr_invalid'
    TYPE_MISSING = 'type_missing'
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
    Validates the SUPERNET's 'dg-supernet-type' selector is set and agrees with the CIDR's
    actual family

    Thin domain-specific binding of the shared ``validate_family_selector`` core (see that
    helper for the required-selector / mismatch semantics) to the SUPERNET selector field,
    detail key and error codes

    Args:
        candidate (Network): The parsed candidate CIDR
        supernet_type (str | None): The 'dg-supernet-type' value ('ipv4' / 'ipv6'), or None
            when the candidate carries no selector value

    Returns:
        list[dict[str, Any]]: A single-element error list on a missing selector or a mismatch,
            empty when consistent
    """
    return validate_family_selector(
        candidate,
        supernet_type,
        selector_field_name=SupernetField.TYPE.value,
        selector_detail_key=IpamValidationDetailKey.SUPERNET_TYPE,
        missing_code=SupernetErrorCode.TYPE_MISSING,
        mismatch_code=SupernetErrorCode.TYPE_FAMILY_MISMATCH,
        subject_label='Supernet',
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ORCHESTRATOR                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def validate_supernet(network_range: str, supernet_type: str | None = None) -> list[dict[str, Any]]:
    """
    Validates a candidate SUPERNET CmdbObject's network range and address family

    Returns the accumulated list of errors so the caller can render or abort. An empty list means
    valid. The ``supernet_type`` selector is required once the CIDR parses: a missing value is
    reported as TYPE_MISSING and a supplied value must agree with the CIDR's actual family. There
    is no parent / sibling / containment check - a supernet stands on its own

    Args:
        network_range (str): The candidate IPv4 or IPv6 CIDR (must be canonical, host bits zeroed)
        supernet_type (str | None): The 'dg-supernet-type' selector ('ipv4' / 'ipv6'); required -
            None is reported as TYPE_MISSING, a given value is cross-checked against the CIDR
            family

    Returns:
        list[dict[str, Any]]: Structured validation errors; empty when the candidate is valid
    """
    candidate, errors = _check_canonical_cidr(network_range)

    if candidate is None:
        return errors

    errors.extend(_check_type_matches_family(candidate, supernet_type))

    return errors
