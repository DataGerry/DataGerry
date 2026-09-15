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
Shared constants for AccessControlLists

Names the keys an ACL document carries, so the model, the CmdbTypes storing an ACL and the type
import stay aligned on the literal strings instead of repeating them
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class AclKey(BaseStrEnum):
    """
    Keys of a stored AccessControlList document

    ACTIVATED switches the whole list on or off; GROUPS is the only section there is today and nests
    its INCLUDES mapping of `{group public_id: [permissions]}`
    """
    ACTIVATED = 'activated'
    GROUPS = 'groups'
    INCLUDES = 'includes'
