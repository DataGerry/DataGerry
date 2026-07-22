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
Project-wide structured-error envelope used by validators

Every validator across the codebase emits errors as a small dict carrying a human-readable
'message', optionally accompanied by a 'details' payload. This module owns both the envelope
shape (named via ValidationErrorKey) and the build_error helper that constructs it, so the
format stays in lockstep across IPAM and any future validator family that adopts it
"""
from typing import Any

from cmdb.utils.base_str_enum import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ValidationErrorKey(BaseStrEnum):
    """
    Top-level keys of a structured validation-error dict

    MESSAGE is the human-readable explanation. DETAILS is an optional payload dict whose keys
    are per-domain (e.g. IpamValidationDetailKey for IPAM); it is present only when a validator
    supplies context (currently just the interface validator's row-index mapping) and is left
    out entirely otherwise
    """
    MESSAGE = 'message'
    DETAILS = 'details'


def build_error(
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Constructs a structured validation-error dict in the project-wide envelope shape

    Always emits MESSAGE; DETAILS is added only when a non-empty context dict is supplied, so an
    error without context stays a bare {message}

    Args:
        message (str): A human-readable explanation
        details (dict[str, Any] | None): Optional context fields the frontend can render; when
            omitted or empty the 'details' key is left out entirely

    Returns:
        dict[str, Any]: {message}, or {message, details} when details is non-empty
    """
    error: dict[str, Any] = {ValidationErrorKey.MESSAGE: message}

    if details:
        error[ValidationErrorKey.DETAILS] = details

    return error
