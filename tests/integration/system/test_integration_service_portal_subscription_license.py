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
Integration tests for DgServicePortalManager.get_subscription_license over real HTTP

A stub Service Portal (a local ``http.server`` on a free port, in a thread) answers ``POST
/datagerry/subscription/License``; the real client sends to it through ``requests``. Pinned: the path, the
``x-access-token`` header, the JSON body the portal team specified, the answer read back as sent, an error status
raised as ``DgServicePortalGetError``, a non-JSON body likewise, and a closed port as ``requests.ConnectionError``.
"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator
from unittest.mock import patch

import pytest
import requests

from cmdb.errors.dg_service_portal import DgServicePortalGetError
from cmdb.manager.system_manager.dg_service_portal_constants import SUBSCRIPTION_LICENSE_URL
from cmdb.manager.system_manager.dg_service_portal_manager import DgServicePortalManager
# -------------------------------------------------------------------------------------------------------------------- #

MANAGER_PATH: str = 'cmdb.manager.system_manager.dg_service_portal_manager'
LOOPBACK: str = '127.0.0.1'
ACCESS_TOKEN: str = 'integration-access-token'
EMAIL: str = 'user@acme.com'
DATABASE: str = 'db_acme'
PORTAL_LICENSE: dict[str, Any] = {
    'databaseName': DATABASE, 'subId': 'SUB-2026-0042', 'licenseId': 'LIC-7f3a9c21', 'type': 'business',
    'features': ['rest_api', 'ipam', 'isms'], 'startDate': 1767225600000, 'endDate': 1798761599000, 'trial': True,
}


class _Portal:
    """What the stub portal answers next, and what it received"""

    def __init__(self) -> None:
        self.status: int = 200
        self.body: bytes = json.dumps(PORTAL_LICENSE).encode()
        self.received: list[dict[str, Any]] = []


def _handler(portal: _Portal) -> type[BaseHTTPRequestHandler]:
    """A request handler recording each POST and answering the portal's next status and body"""

    class _Handler(BaseHTTPRequestHandler):
        """The stub Service Portal"""

        def do_POST(self) -> None:  # pylint: disable=invalid-name
            """Records the request, answers the configured response"""
            length: int = int(self.headers.get('Content-Length', 0))
            portal.received.append({
                'path': self.path, 'token': self.headers.get('x-access-token'),
                'body': json.loads(self.rfile.read(length) or b'null'),
            })
            self.send_response(portal.status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(portal.body)

        def log_message(self, *_args: Any) -> None:
            """Quiet"""

    return _Handler


@pytest.fixture(name='portal')
def fixture_portal() -> Iterator[tuple[_Portal, str]]:
    """A running stub portal and its base URL"""
    portal = _Portal()
    server = ThreadingHTTPServer((LOOPBACK, 0), _handler(portal))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield portal, f'http://{LOOPBACK}:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def _manager(base_url: str) -> DgServicePortalManager:
    """The real client, pointed at ``base_url`` without reading the environment"""
    with patch(f'{MANAGER_PATH}.is_hosted_cloud', return_value=False):
        manager = DgServicePortalManager()
    manager.base_url = base_url
    manager.x_access_token = ACCESS_TOKEN
    return manager


def test_the_request_the_portal_team_specified(portal) -> None:
    """Path, token header and body"""
    stub, base_url = portal

    _manager(base_url).get_subscription_license(EMAIL, DATABASE)

    assert stub.received == [{
        'path': SUBSCRIPTION_LICENSE_URL, 'token': ACCESS_TOKEN,
        'body': {'userEmail': EMAIL, 'databaseName': DATABASE},
    }]


def test_the_answer_is_read_back_as_sent(portal) -> None:
    """The portal team's example"""
    _stub, base_url = portal

    assert _manager(base_url).get_subscription_license(EMAIL, DATABASE) == PORTAL_LICENSE


@pytest.mark.parametrize('status, body', [(404, b'{"message": "no subscription"}'), (200, b'not json')],
                         ids=['error-status', 'not-json'])
def test_an_unusable_answer_is_a_get_error(portal, status: int, body: bytes) -> None:
    """Raised for the route's 502"""
    stub, base_url = portal
    stub.status, stub.body = status, body

    with pytest.raises(DgServicePortalGetError):
        _manager(base_url).get_subscription_license(EMAIL, DATABASE)


def test_a_closed_port_is_a_connection_error() -> None:
    """Raised for the route's 503"""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        closed_port: int = probe.getsockname()[1]

    with pytest.raises(requests.ConnectionError):
        _manager(f'http://{LOOPBACK}:{closed_port}').get_subscription_license(EMAIL, DATABASE)
