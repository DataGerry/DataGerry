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
Implementation of general helper functions
"""

def boolify(s: str) -> bool:
    """
    Converts a string representation of a boolean to its corresponding boolean value
    
    Args:
        s (str): The string to be converted

    Raises:
        ValueError: If the input string is not a valid boolean representation

    Returns:
        bool: True if 'True' or 'true', False if 'False' or 'false'
    """
    if s in ('True', 'true'):
        return True
    if s in ('False', 'false'):
        return False

    raise ValueError(f"Invalid boolean value: {s}")


def noneify(s: str) -> None:
    """
    Converts a string representation of 'None' to a NoneType value
    
    Args:
        s (str): The string to be converted

    Raises:
        ValueError: If the input string is not a valid representation of None

    Returns:
        None: If the input string is 'None' or 'null'
    """
    if s in ('None', 'null'):
        return None

    raise ValueError(f"Invalid None value: {s}")


def auto_cast(val: str) -> float | int | str | bool | None:
    """
    Attempts to automatically convert a string into its most appropriate data type
    
    Tries the following conversions in order:
    - Boolean (True/False)
    - Integer
    - NoneType (None)
    - Float
    - String (fallback)
    
    Args:
        val (str): The value to be converted
    
    Returns:
        bool | int | None | float | str: The converted value
    """
    for caster in (boolify, int, noneify, float, str):
        try:
            return caster(val)
        except (ValueError, TypeError):
            pass

    return val
