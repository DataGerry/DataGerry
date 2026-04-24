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
from cmdb.models.docapi_model.safe_null import SafeNull
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  SafeObject - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class SafeObject:
    """TODO: document"""
    def __getattr__(self, name):
        return SafeNull()

    def __getitem__(self, key):
        return SafeNull()

    def get(self, *args, **kwargs):
        """TODO: document"""
        return SafeNull()

    def __str__(self):
        return "\u00A0"

    def __repr__(self):
        return "\u00A0"

    def __html__(self):
        return "&nbsp;"

    def __bool__(self):
        return False
