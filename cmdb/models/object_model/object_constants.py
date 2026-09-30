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
Constants shared by the CmdbObject write paths
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ObjectWriteVerb(BaseStrEnum):
    """
    The verb a refused CmdbObject write names in its message

    `ObjectsManager.guard_writable_type` refuses a write on a deactivated type with *"Objects cannot be
    <verb> because type ... is deactivated"*; the manager's own writes and the routes that ask the guard
    before their side effects pass the same verb, so a refusal reads the same whichever step raised it
    """
    CREATED = 'created'
    UPDATED = 'updated'
    REMOVED = 'removed'
