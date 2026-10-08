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
Unit tests for cmdb.interface.rest_api.routes.webhook_routes.webhook_destination, and for the delivery's use of it

  - every non-public range is refused, an IPv4-mapped IPv6 address by the IPv4 address it carries; public unicast
    passes; the check runs on the RESOLVED addresses, so encoded spellings of 127.0.0.1 are refused too
  - a host that does not resolve is not judged; an invalid port is refused
  - allowed_hosts lets a host through by name (any case) or every one of its addresses by network
  - the delivery judges the destination again and does not send to a refused one; it never follows a redirect
"""
import ipaddress
import socket
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.interface.rest_api.routes.webhook_routes import webhook_destination, webhook_helper
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import (
    WEBHOOK_NO_RESPONSE_CODE,
    WebhookDestinationReason,
)
from cmdb.interface.rest_api.routes.webhook_routes.webhook_destination import (
    is_public_address,
    refused_destination_reason,
)
# -------------------------------------------------------------------------------------------------------------------- #

NOT_PUBLIC: list[str] = [
    '127.0.0.1', '10.1.2.3', '172.16.0.1', '192.168.1.1', '169.254.169.254', '100.64.0.1', '0.0.0.0', '224.0.0.1',
    '192.0.2.1', '240.0.0.1', '::1', 'fc00::1', 'fe80::1', 'ff02::1', '::ffff:127.0.0.1', '::ffff:10.0.0.1',
]
PUBLIC: list[str] = ['8.8.8.8', '1.1.1.1', '2606:4700:4700::1111', '::ffff:8.8.8.8']


def _resolving_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    """Makes every lookup answer ``addresses``"""
    infos = [(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 80))
             for address in addresses]
    monkeypatch.setattr(webhook_destination.socket, 'getaddrinfo', lambda *_args, **_kwargs: infos)


class TestIsPublicAddress:
    """The classifier"""

    @pytest.mark.parametrize('address', NOT_PUBLIC)
    def test_a_non_public_address_is_refused(self, address: str) -> None:
        """Loopback, private, link-local, shared, unspecified, multicast, reserved, documentation"""
        assert not is_public_address(ipaddress.ip_address(address))

    @pytest.mark.parametrize('address', PUBLIC)
    def test_a_public_unicast_address_passes(self, address: str) -> None:
        """IPv4, IPv6 and an IPv4-mapped public address"""
        assert is_public_address(ipaddress.ip_address(address))


class TestRefusedDestinationReason:
    """Judging a URL"""

    @pytest.mark.parametrize('url', ['http://127.0.0.1:27017/', 'http://2130706433/', 'http://0x7f.1/',
                                     'http://[::1]/', 'http://localhost/hook'])
    def test_a_loopback_destination_is_refused_however_it_is_spelled(self, url: str) -> None:
        """Judged on what it resolves to, not on its text"""
        reason = refused_destination_reason(url)

        assert reason is not None and ('127.0.0.1' in reason or '::1' in reason)

    def test_one_non_public_address_among_public_ones_refuses(self, monkeypatch) -> None:
        """Any address the server could connect to counts"""
        _resolving_to(monkeypatch, '8.8.8.8', '10.0.0.5')

        assert refused_destination_reason('http://mixed.example/') == WebhookDestinationReason.NOT_PUBLIC.value.format(
            host='mixed.example', addresses='10.0.0.5')

    def test_a_public_destination_passes(self, monkeypatch) -> None:
        """Nothing to refuse"""
        _resolving_to(monkeypatch, '8.8.8.8')

        assert refused_destination_reason('https://receiver.example/hook') is None

    def test_a_host_that_does_not_resolve_is_not_judged(self) -> None:
        """Nothing can be delivered to it - the delivery fails as it always did"""
        assert refused_destination_reason('http://example.test/hook') is None

    def test_a_url_without_a_host_is_refused(self) -> None:
        """Only reachable through a direct call - the save check refuses it earlier"""
        assert refused_destination_reason('http:///hook') == WebhookDestinationReason.NO_HOST.value

    def test_an_invalid_port_is_refused(self) -> None:
        """urlsplit raises on reading it"""
        assert refused_destination_reason('http://receiver.example:99999/') == \
            WebhookDestinationReason.INVALID_PORT.value

    def test_the_port_defaults_by_scheme(self, monkeypatch) -> None:
        """443 for https, 80 for http"""
        lookups: list[Any] = []
        monkeypatch.setattr(webhook_destination.socket, 'getaddrinfo',
                            lambda host, port, **_kwargs: lookups.append(port) or [])

        refused_destination_reason('https://a.example/')
        refused_destination_reason('http://a.example/')

        assert lookups == [443, 80]

    @pytest.mark.parametrize('allowed', [['LOCALHOST'], ['127.0.0.0/8'], ['127.0.0.1']],
                             ids=['by-name', 'by-network', 'by-single-address'])
    def test_an_allowed_host_passes(self, allowed: list[str]) -> None:
        """By name in any case, or every address inside an allowed network"""
        assert refused_destination_reason('http://localhost/hook', allowed) is None

    def test_an_allowed_network_must_hold_every_address(self, monkeypatch) -> None:
        """One address outside it still refuses"""
        _resolving_to(monkeypatch, '10.0.0.5', '192.168.1.5')

        assert refused_destination_reason('http://inner.example/', ['10.0.0.0/8']) is not None


class TestTheDelivery:
    """deliver_webhook_event"""

    @staticmethod
    def _deliver(monkeypatch, post: Any, refused: str | None) -> MagicMock:
        """Delivers one payload with the destination judged as given; answers the event manager"""
        monkeypatch.setattr(webhook_helper, 'refused_destination_reason', lambda _url: refused)
        monkeypatch.setattr(webhook_helper.requests, 'post', post)
        events = MagicMock()
        webhook_helper.deliver_webhook_event(SimpleNamespace(url='http://receiver.example/', public_id=7),
                                             {'operation': 'CREATE'}, events)
        return events

    def test_a_refused_destination_is_not_sent_and_recorded_as_failed(self, monkeypatch) -> None:
        """Judged again at delivery: the host may resolve differently now"""
        post = MagicMock()

        events = self._deliver(monkeypatch, post, "'receiver.example' resolves to ...")

        post.assert_not_called()
        stored: dict[str, Any] = events.insert_item.call_args.args[0]
        assert (stored['response_code'], stored['status']) == (WEBHOOK_NO_RESPONSE_CODE, False)

    def test_a_redirect_is_never_followed(self, monkeypatch) -> None:
        """A 3xx is recorded with its code, not delivered"""
        post = MagicMock(return_value=SimpleNamespace(status_code=307))

        events = self._deliver(monkeypatch, post, None)

        assert post.call_args.kwargs['allow_redirects'] is False
        stored: dict[str, Any] = events.insert_item.call_args.args[0]
        assert (stored['response_code'], stored['status']) == (307, False)
