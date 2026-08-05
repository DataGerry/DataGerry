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
All general helper methods for Document Generator
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

def mm_to_pt(value: float, default: float) -> int:
    """Convert mm to pt (rounded)"""
    try:
        if not value:
            return default

        return int(float(value) * 2.83465)
    except (TypeError, ValueError):
        return default


def format_value(prop: str, value: Any) -> str:
    """TODO: document"""
    if prop == "line-height":
        return str(value)  # unitless

    if isinstance(value, (int, float)):
        return f"{value}pt"

    return str(value)
