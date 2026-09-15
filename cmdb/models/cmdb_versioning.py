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
Module for versioning CmdbObjects and CmdbTypes
"""
from logging import Logger, getLogger

from cmdb.errors.cmdb_object import VersionTypeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  Versioning - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class Versioning:
    """
    A helper class for managing CmdbObjects/CmdbTypes versioning using Semantic Versioning (major.minor.patch).

    This class provides attributes and methods to track and update version numbers
    """

    def __init__(self, major: int = 1, minor: int = 0, patch: int = 0):
        """
        Initializes a version instance

        Args:
            major (int): Indicates significant changes that break backward compatibility
            minor (int): Indicates new features that are backward-compatible
            patch (int): Indicates backward-compatible bug fixes or small changes
        """
        self.major = major
        self.minor = minor
        self.patch = patch


    def __repr__(self) -> str:
        """Returns the version as a formatted string"""
        return f"{self.major}.{self.minor}.{self.patch}"


    @property
    def major(self) -> int:
        """Gets the major version number"""
        return self._major


    @major.setter
    def major(self, value: int):
        if not isinstance(value, int):
            raise VersionTypeError(f"Invalid 'major' version type: {value} (expected int).")

        self._major = value


    @property
    def minor(self) -> int:
        """Gets the minor version number"""
        return self._minor


    @minor.setter
    def minor(self, value: int):
        if not isinstance(value, int):
            raise VersionTypeError(f"Invalid 'minor' version type: {value} (expected int).")

        self._minor = value


    @property
    def patch(self) -> int:
        """Gets the patch version number"""
        return self._patch


    @patch.setter
    def patch(self, value: int):
        if not isinstance(value, int):
            raise VersionTypeError(f"Invalid 'patch' version type: {value} (expected int).")

        self._patch = value


    def update_major(self) -> int:
        """
        Increments the major version and resets the minor and patch components

        Semantic versioning: a major release starts a new line, so 1.2.3 becomes 2.0.0 rather than
        2.2.3 - carrying the old minor and patch forward made the string read as if changes had
        accumulated within a line that had just been replaced

        Returns:
            int: Updated major version
        """
        self.major += 1
        self.minor = 0
        self.patch = 0

        return self.major


    def update_minor(self) -> int:
        """
        Increments the minor version and resets the patch component

        Semantic versioning, and what this docstring already promised: 1.2.3 becomes 1.3.0. The reset
        was missing, so a series of edits produced strings like 1.5.7 where the patch count belonged
        to a minor version two releases old

        Returns:
            int: Updated minor version
        """
        self.minor += 1
        self.patch = 0

        return self.minor


    def update_patch(self) -> int:
        """
        Increments the patch version

        Returns:
            int: Updated patch version
        """
        self.patch += 1
        return self.patch
