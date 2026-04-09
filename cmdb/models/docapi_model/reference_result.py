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

from cmdb.models.docapi_model.safe_dict import SafeDict
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ReferenceResult - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class RefResult:
    """
    Wrapper for a resolved reference field to allow type filtering in templates.
    """
    def __init__(self, obj_data: dict | None):
        self.obj_data = obj_data or {}

    def type(self, type_id: int):
        """TODO. document"""
        try:
            if not self.obj_data:
                return SafeDict({})

            obj_type_id = self.obj_data.get("type_id")

            if obj_type_id == type_id:
                return SafeDict(self.obj_data)

            return SafeDict({})
        except Exception:
            return SafeDict({})

    def __getitem__(self, key):
        try:
            value = self.obj_data.get(key)
            if isinstance(value, dict):
                return SafeDict(value)
            return value if value is not None else SafeDict({})
        except Exception:
            return SafeDict({})

    def get(self, key, default=None):
        """TODO. document"""
        try:
            value = self.obj_data.get(key, default)
            if isinstance(value, dict):
                return SafeDict(value)
            return value
        except Exception:
            return default
