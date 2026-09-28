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
The assertions every update route's functional tests share

An update route's response must be the document as it now sits in the database, not the request
body - so a key the caller left out, or sent as ``null``, comes back as the value the model stored for
it. ``put_and_read_back`` sends the update and reads the stored document through the entity's own
single read, so the comparison is between the two things a client can see.

An update is also addressed by the URL alone: a ``public_id`` in the body must not move the stored
document to another id. ``assert_body_public_id_cannot_move`` sends such a body and checks both ids
in the collection itself
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


def assert_body_public_id_cannot_move(rest_api: Any, url: str, payload: dict[str, Any],
                                      collection: Any, stored_id: int, method: str = 'put') -> None:
    """
    Sends an update whose body names another public_id and asserts the stored document stays put

    Args:
        rest_api: The functional test client
        url (str): The update route of the stored document
        payload (dict[str, Any]): A valid update body whose ``public_id`` differs from ``stored_id``
        collection: The document's MongoDB collection, read directly
        stored_id (int): The public_id the URL addresses
        method (str): The test-client method the route answers, ``put`` or ``patch``
    """
    forged_id: Any = payload['public_id']
    assert forged_id != stored_id, 'the body must name a different public_id'

    response = getattr(rest_api, method)(url, json=payload)

    assert response.status_code in UPDATE_STATUSES
    assert collection.find_one({'public_id': forged_id}) is None
    assert collection.find_one({'public_id': stored_id}) is not None
