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
The types and users several renders of one request share

A bulk write renders one edit log per object it writes, and every render reads the same type and the same users.
Handed one ``RenderLookups``, each ``CmdbMultiRender`` starts from what the earlier ones read and adds what it reads
itself - its lookups only fetch the ids they do not hold yet. Only types and users are shared: neither can change
while an object write runs. The objects a render references are not - a bulk write can change an object that a later
target references, and each render reads them through its own read scope
"""
from dataclasses import dataclass, field

from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

@dataclass
class RenderLookups:
    """
    The type and user lookups shared by the renders of one request, filled in place

    Attributes:
        types (dict[int, CmdbType]): The CmdbTypes read so far, by public_id
        users (dict[int, CmdbUser]): The CmdbUsers read so far, by public_id
    """
    types: dict[int, CmdbType] = field(default_factory=dict)
    users: dict[int, CmdbUser] = field(default_factory=dict)
