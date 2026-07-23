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
This file contains all helper methods for OpenCelium
"""

def map_oc_name(map_name: str, input_str: str) -> str:
    """
    Prefixes `input_str` with `map_name` so OpenCelium names are scoped to a tenant

    Args:
        map_name (str): the prefix the input is scoped with (e.g. the tenant database name)
        input_str (str): the original string

    Returns:
        str: the mapped string in the format `<map_name>_<input_str>`
    """
    return f"{map_name}_{input_str}"


def unmap_oc_name(mapped_str: str, strict: bool = True) -> str:
    """
    Reverses `map_oc_name`, stripping the leading `<map_name>_` prefix

    Only the first underscore is split on, so a value that itself contains underscores is restored
    intact (`'db_a_b'` -> `'a_b'`). This assumes the prefix carries no underscore.

    Args:
        mapped_str (str): the previously mapped string to unmap
        strict (bool): when True a string without an underscore is rejected; when False such a
            string is returned unchanged. Defaults to True

    Raises:
        ValueError: if `strict` is True and `mapped_str` contains no underscore "_"

    Returns:
        str: the unmapped string (the part after the first underscore)
    """
    if "_" not in mapped_str:
        if strict:
            raise ValueError(f"Invalid mapped string: {mapped_str!r}. It contains no underscore.")

        return mapped_str

    return mapped_str.split("_", 1)[1]
