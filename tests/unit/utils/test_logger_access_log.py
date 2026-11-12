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
Unit tests for the gunicorn access log setup

The access log always goes to its rotating file; `DG_ACCESS_LOG_CONSOLE` mirrors it to the console so the hosted
backend's request lines reach the container log. The HTTP server's default access log format carries the request
duration, while an access_log_format from cmdb.conf still wins
"""
from unittest.mock import MagicMock

import pytest

from cmdb.database.database_constants import KEEPALIVE_PING_INTERVAL_SECONDS, MONGO_MAX_IDLE_TIME_MS
from cmdb.interface.http_server import ACCESS_LOG_FORMAT, HTTPServer
from cmdb.utils.logger import ACCESS_LOG_CONSOLE_ENV, access_log_to_console, get_logging_conf
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('value', ['1', 'true', 'TRUE', 'yes', ' Yes '])
def test_access_log_console_is_enabled_by_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """1/true/yes in any case turn the console mirror on."""
    monkeypatch.setenv(ACCESS_LOG_CONSOLE_ENV, value)

    assert access_log_to_console() is True
    assert get_logging_conf()['loggers']['gunicorn.access']['handlers'] == ['file_web_access', 'console']


@pytest.mark.parametrize('value', [None, '', '0', 'false', 'no', 'console'])
def test_access_log_stays_in_its_file_by_default(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    """Unset or any other value keeps the on-premise behaviour: the access log only goes to its file."""
    if value is None:
        monkeypatch.delenv(ACCESS_LOG_CONSOLE_ENV, raising=False)
    else:
        monkeypatch.setenv(ACCESS_LOG_CONSOLE_ENV, value)

    assert access_log_to_console() is False
    assert get_logging_conf()['loggers']['gunicorn.access']['handlers'] == ['file_web_access']


def test_default_access_log_format_contains_the_request_duration() -> None:
    """Without an access_log_format in cmdb.conf the request duration in milliseconds is logged."""
    server = HTTPServer(MagicMock(), {'host': '127.0.0.1', 'port': 4000, 'workers': 1})

    assert server.cfg.access_log_format == ACCESS_LOG_FORMAT
    assert '%(M)s' in ACCESS_LOG_FORMAT


def test_access_log_format_from_the_config_wins() -> None:
    """An access_log_format from the WebServer section of cmdb.conf is not overridden."""
    server = HTTPServer(MagicMock(), {'host': '127.0.0.1', 'port': 4000, 'workers': 1,
                                      'access_log_format': '%(r)s %(s)s'})

    assert server.cfg.access_log_format == '%(r)s %(s)s'


def test_pooled_connections_outlive_the_keepalive_ping() -> None:
    """A pooled connection must not expire between two keep-alive pings, or every ping reconnects."""
    assert MONGO_MAX_IDLE_TIME_MS > KEEPALIVE_PING_INTERVAL_SECONDS * 1000
