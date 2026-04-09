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
#                                                   SafeDict - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class SafeDict(dict):
    """TODO: document"""
    def __getitem__(self, key):
        try:
            value = super().get(key)
            return self._wrap(value)
        except Exception:
            return super().get(key, SafeNull())

    def get(self, key, default=""):
        try:
            value = super().get(key, default)
            return self._wrap(value)
        except Exception:
            return super().get(key, SafeNull())

    def __getattr__(self, name):
        value = super().get(name, None)
        return self._wrap(value)

    def _wrap(self, value):
        if value is None:
            return SafeNull()

        if isinstance(value, dict):
            return SafeDict(value)

        if isinstance(value, list):
            return [self._wrap(v) for v in value]

        return value
