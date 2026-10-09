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
Integration tests for where a webhook delivers to, against real HTTP servers on the loopback interface

  - a delivery to a loopback receiver is not sent: the receiver sees no request, the event records a failure
  - the same receiver, once its network is allowed, gets the POST and the event records the delivery
  - an allowed receiver that answers with a redirect to another loopback server is not followed: the second server
    sees no request, and the event records the 3xx as not delivered
"""
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.interface.rest_api.routes.webhook_routes import webhook_helper
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WEBHOOK_NO_RESPONSE_CODE
from cmdb.interface.rest_api.routes.webhook_routes.webhook_destination import refused_destination_reason
# -------------------------------------------------------------------------------------------------------------------- #

LOOPBACK: str = '127.0.0.1'
LOOPBACK_NETWORK: str = '127.0.0.0/8'
REDIRECT_STATUS: int = 307
WEBHOOK_ID: int = 4711


def _receiver(answer_status: int = 200, location: str | None = None) -> tuple[HTTPServer, list[str]]:
    """A loopback HTTP server recording the paths it was POSTed to, answering ``answer_status``"""
    received: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # pylint: disable=invalid-name
            """Records the request and answers"""
            received.append(self.path)
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(answer_status)

            if location:
                self.send_header('Location', location)

            self.end_headers()

        def log_message(self, *_args: Any) -> None:
            """Silent"""

    server = HTTPServer((LOOPBACK, 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    return server, received


@pytest.fixture(name='servers')
def fixture_servers() -> Iterator[dict[str, Any]]:
    """A plain receiver, and a redirecting one pointing at a second receiver"""
    target, target_received = _receiver()
    second, second_received = _receiver()
    redirecting, redirect_received = _receiver(
        REDIRECT_STATUS, f'http://{LOOPBACK}:{second.server_address[1]}/redirected',
    )
    yield {
        'target': (target, target_received),
        'second': (second, second_received),
        'redirecting': (redirecting, redirect_received),
    }
    for server in (target, second, redirecting):
        server.shutdown()
        server.server_close()


def _url(server: HTTPServer) -> str:
    """The server's URL"""
    return f'http://{LOOPBACK}:{server.server_address[1]}/hook'


def _deliver(url: str) -> dict[str, Any]:
    """One real delivery; answers the event it recorded"""
    events = MagicMock()
    webhook_helper.deliver_webhook_event(SimpleNamespace(url=url, public_id=WEBHOOK_ID), {'operation': 'CREATE'},
                                         events)
    return events.insert_item.call_args.args[0]


def _allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """What an operator allowlist of the loopback network would do"""
    monkeypatch.setattr(webhook_helper, 'refused_destination_reason',
                        lambda url: refused_destination_reason(url, [LOOPBACK_NETWORK]))


def test_a_loopback_receiver_is_not_sent_to(servers: dict[str, Any]) -> None:
    """Refused before any connection: the receiver sees nothing"""
    server, received = servers['target']

    event = _deliver(_url(server))

    assert received == []
    assert (event['response_code'], event['status']) == (WEBHOOK_NO_RESPONSE_CODE, False)


def test_an_allowed_receiver_gets_the_delivery(monkeypatch, servers: dict[str, Any]) -> None:
    """The allowlist is the operator's way through"""
    _allow_loopback(monkeypatch)
    server, received = servers['target']

    event = _deliver(_url(server))

    assert received == ['/hook']
    assert (event['response_code'], event['status']) == (200, True)


def test_a_redirect_is_not_followed(monkeypatch, servers: dict[str, Any]) -> None:
    """The second server - which nobody judged - sees nothing"""
    _allow_loopback(monkeypatch)
    redirecting, redirect_received = servers['redirecting']
    _second, second_received = servers['second']

    event = _deliver(_url(redirecting))

    assert redirect_received == ['/hook']
    assert second_received == []
    assert (event['response_code'], event['status']) == (REDIRECT_STATUS, False)
