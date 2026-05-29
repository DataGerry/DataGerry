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

Every validator across the codebase emits errors as a small dict with three fixed top-level
keys (code / message / details). This module owns both the envelope shape (named via
ValidationErrorKey) and the build_error helper that constructs it, so the format stays in
lockstep across IPAM and any future validator family that adopts the same convention
"""
from typing import Any

from cmdb.utils.base_str_enum import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ValidationErrorKey(BaseStrEnum):
    """
    Top-level keys of a structured validation-error dict

    CODE is the stable machine-readable identifier (typically a member of an XxxErrorCode
    enum). MESSAGE is the human-readable explanation. DETAILS is an optional payload dict
    whose keys are per-domain (e.g. IpamValidationDetailKey for IPAM)
    """
    CODE = 'code'
    MESSAGE = 'message'
    DETAILS = 'details'


def build_error(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Constructs a structured validation-error dict in the project-wide envelope shape

    Always emits the three keys CODE / MESSAGE / DETAILS so consumers (validation routes, the
    frontend, tests) can rely on the shape without conditional defaults

    Args:
        code (str): A stable machine-readable error code (typically a BaseStrEnum member)
        message (str): A human-readable explanation
        details (dict[str, Any] | None): Optional context fields the frontend can render; when
            omitted, an empty dict is emitted so the 'details' key is always present

    Returns:
        dict[str, Any]: The error dict with keys ValidationErrorKey.CODE, .MESSAGE, .DETAILS
    """
    return {
        ValidationErrorKey.CODE: code,
        ValidationErrorKey.MESSAGE: message,
        ValidationErrorKey.DETAILS: details or {},
    }
