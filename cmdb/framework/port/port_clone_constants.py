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
Constants of cloning a CmdbObject's ports onto its copy
"""
from cmdb.models.port_model import PortKey
from cmdb.models.port_model.port_constants import PORT_TEMPLATE_FIELD_KEYS
# -------------------------------------------------------------------------------------------------------------------- #

# What a cloned port takes from its source: the face it sits on and every user-facing field. Its id, its owner,
# its author and its timestamps are the clone's own
CLONED_PORT_KEYS: tuple[PortKey, ...] = (PortKey.SIDE, *PORT_TEMPLATE_FIELD_KEYS)
