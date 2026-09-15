# DataGerry - OpenSource Enterprise CMDB
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
Implementation of safe_wrap

Shared helper that recursively wraps template data for DocAPI rendering: dicts become `SafeDict`
and lists have their elements wrapped, so any missing key/attribute encountered while rendering
resolves to a blank `SafeNull` instead of raising. Used by both `TemplateEngine` and
`DefaultTemplateData` (previously duplicated as a private ``_safe_wrap`` in each).
"""
from typing import Any

from cmdb.models.docapi_model.safe_dict import SafeDict
# -------------------------------------------------------------------------------------------------------------------- #


def safe_wrap(data: Any) -> Any:
    """
    Recursively wraps template data so nested lookups stay render-safe

    A dict is wrapped as a `SafeDict` (its values wrapped recursively), a list has each element
    wrapped, and any other value is returned unchanged.

    Args:
        data (Any): The raw template data to wrap

    Returns:
        Any: The wrapped data — a `SafeDict` for a dict, a list of wrapped elements for a list,
            otherwise the value unchanged
    """
    if isinstance(data, dict):
        return SafeDict({key: safe_wrap(value) for key, value in data.items()})

    if isinstance(data, list):
        return [safe_wrap(value) for value in data]

    return data
