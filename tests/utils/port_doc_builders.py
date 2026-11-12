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
Stored-document builders for ports, port connections and the objects that own them, for tests that seed a real
MongoDB (the CI Explorer's port source and the routes above it)
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey
from cmdb.models.port_model import PortKey, PortSide
# -------------------------------------------------------------------------------------------------------------------- #


def port_doc(public_id: int, object_id: int, side: str = PortSide.SINGLE.value) -> dict[str, Any]:
    """A stored CmdbPort document"""
    return {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: side,
        PortKey.NAME.value: f'port-{public_id}',
        PortKey.PORT_NUMBER.value: None,
        PortKey.STATUS.value: None,
        PortKey.PORT_TYPE.value: None,
        PortKey.SPEED.value: None,
        PortKey.DESCRIPTION.value: None,
        PortKey.AUTHOR_ID.value: 1,
        PortKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortKey.LAST_EDIT_TIME.value: None,
    }


def cable_doc(public_id: int, endpoints: list[int]) -> dict[str, Any]:
    """A stored CABLE CmdbPortConnection; the endpoints sorted as the model sorts them on write"""
    return {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: sorted(endpoints),
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
        PortConnectionKey.CABLE_NAME.value: None,
        PortConnectionKey.CABLE_TYPE.value: None,
        PortConnectionKey.CABLE_LENGTH.value: None,
        PortConnectionKey.CABLE_COLOR.value: None,
        PortConnectionKey.CABLE_DESCRIPTION.value: None,
        PortConnectionKey.AUTHOR_ID.value: 1,
        PortConnectionKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortConnectionKey.LAST_EDIT_TIME.value: None,
    }


def device_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """A stored, active CmdbObject a cable can end on"""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'name': 'dg-name', 'value': f'device-{public_id}', 'type': 'text'}],
        'multi_data_sections': [],
    }
