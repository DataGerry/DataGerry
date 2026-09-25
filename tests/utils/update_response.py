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
The one assertion every update route's functional tests share: the update answers what was stored

An update route's response must be the document as it now sits in the database, not the request
body - so a key the caller left out, or sent as ``null``, comes back as the value the model stored for
it. ``put_and_read_back`` sends the update and reads the stored document through the entity's own
single read, so the comparison is between the two things a client can see
"""
from http import HTTPStatus
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

UPDATE_STATUSES: tuple[HTTPStatus, ...] = (HTTPStatus.OK, HTTPStatus.ACCEPTED)


def put_and_read_back(rest_api: Any, url: str, payload: dict[str, Any], read_url: str | None = None) -> tuple[Any, Any]:
    """
    Sends an update and reads the updated document back

    Args:
        rest_api: The functional test client
        url (str): The update route
        payload (dict[str, Any]): The update body
        read_url (str | None): The single read of the same document; the update route when None

    Returns:
        tuple[Any, Any]: The update response's ``result`` and the single read's ``result``
    """
    response = rest_api.put(url, json=payload)

    assert response.status_code in UPDATE_STATUSES, response.get_json()

    return response.get_json()['result'], rest_api.get(read_url or url).get_json()['result']
