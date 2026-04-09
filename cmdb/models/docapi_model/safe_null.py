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
TODO: document
"""
from logging import Logger, getLogger
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   SafeNull - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class SafeNull:
    """
    Absorbs any access and returns itself or empty string
    """
    def type(self, *args, **kwargs):
        """TODO: document"""
        return self

    def __getitem__(self, key):
        return self

    def get(self, *args, **kwargs):
        """TODO: document"""
        return self

    def __getattr__(self, name):
        return self

    def __str__(self):
        return ""

    def __repr__(self):
        return ""

    def __bool__(self):
        return False
