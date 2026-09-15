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
This module contains the classes of all errors raised by the project-wide utils package
"""
# -------------------------------------------------------------------------------------------------------------------- #

class UtilsError(Exception):
    """
    Raised to catch all errors of the project-wide utils package
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all errors of the project-wide utils package
        """
        super().__init__(err)

# -------------------------------------------------- Utils - ERRORS -------------------------------------------------- #

class ClassLoadError(UtilsError):
    """
    Error if a dotted `pkg.module.ClassName` path could not be resolved to a class

    Raised by `load_class` when the path carries no dot at all, so it cannot be split into a module
    and an attribute. An import failure of the module portion, or a missing attribute on it, still
    surfaces as the underlying `ModuleNotFoundError` / `AttributeError`
    """
