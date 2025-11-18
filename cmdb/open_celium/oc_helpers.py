# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
    map the 'input_str' with the given 'map_name'

    Args:
        map_name (str): the name with which the input should be mapped
        input_str (str): the original string

    Returns:
        str: the mappen string in format <map_name>_<input_str>
    """
    return f"{map_name}_{input_str}"


def unmap_oc_name(mapped_str: str) -> str:
    """
    Unmaps a given string which was mapped with the 'map_oc_name' function

    Args:
        mapped_str (str): the string which should be unmapped

    Raises:
        ValueError: if the mapped_str does not contain an underscore "_"

    Returns:
        str: the unmapped string
    """
    if "_" not in mapped_str:
        raise ValueError(f"Invalid mapped string: {mapped_str!r}. It contains no underscore.")

    parts: list[str] = mapped_str.split("_", 1)

    return parts[1]
