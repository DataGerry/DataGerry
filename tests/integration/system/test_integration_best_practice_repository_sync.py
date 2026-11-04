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
Integration tests for the best-practice repository sync over real HTTP

A stub GitHub (a local ``http.server`` on a free port, in a thread) answers the tarball endpoint the way GitHub does:
a 302 to a download URL carrying a temporary token in its query string, which answers the archive. The real sync sends
to it through ``requests`` and writes into ``tmp_path``. Pinned: the path for the default branch and for a ref, the
headers (the token as Bearer, the API version), the redirect followed, the folder mirrored, a refusing GitHub and a
closed port as one WARNING with nothing changed, and that neither token reaches the log
"""
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from cmdb.framework.configuration_transfer import RepositorySyncReport, sync_best_practice_repository
from cmdb.framework.configuration_transfer import best_practice_repository
from cmdb.framework.configuration_transfer.best_practice_repository_constants import BestPracticeRepositoryEnv

from tests.utils.best_practice_repository_fixture import REPOSITORY, TOKEN, build_archive
# -------------------------------------------------------------------------------------------------------------------- #

LOOPBACK: str = '127.0.0.1'
DOWNLOAD_TOKEN: str = 'temporary-download-token-42'
DOWNLOAD_PATH: str = f'/codeload/{REPOSITORY}/legacy.tar.gz'
FIRST_FILE: str = 'clients.json'
FIRST_CONTENT: bytes = b'{"clients": true}'
STALE_FILE: str = 'stale.json'
ENVIRON: dict[str, str] = {
    BestPracticeRepositoryEnv.REPOSITORY.value: REPOSITORY, BestPracticeRepositoryEnv.TOKEN.value: TOKEN,
}
REPOSITORY_LOGGER: str = best_practice_repository.LOGGER.name


class _GitHub:
    """What the stub answers next, and what it received"""

    def __init__(self) -> None:
        self.status: int = 200
        self.archive: bytes = build_archive({FIRST_FILE: FIRST_CONTENT, 'README.md': b'readme'})
        self.received: list[dict[str, Any]] = []


def _handler(github: _GitHub) -> type[BaseHTTPRequestHandler]:
    """A handler: the tarball endpoint redirects to the download, the download answers the archive"""

    class _Handler(BaseHTTPRequestHandler):
        """The stub GitHub"""

        def do_GET(self) -> None:  # pylint: disable=invalid-name
            """Records the request, redirects or answers"""
            github.received.append({'path': self.path, 'headers': dict(self.headers)})

            if self.path.startswith(DOWNLOAD_PATH):
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-gzip')
                self.send_header('Content-Length', str(len(github.archive)))
                self.end_headers()
                self.wfile.write(github.archive)
                return

            if github.status != 200:
                self.send_response(github.status)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return

            self.send_response(302)
            self.send_header('Location', f'{DOWNLOAD_PATH}?token={DOWNLOAD_TOKEN}')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *_args: Any) -> None:
            """Quiet"""

    return _Handler


@pytest.fixture(name='github')
def fixture_github() -> Iterator[tuple[_GitHub, str]]:
    """A running stub GitHub and its base URL"""
    github = _GitHub()
    server = ThreadingHTTPServer((LOOPBACK, 0), _handler(github))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield github, f'http://{LOOPBACK}:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Everything the sync logged"""
    return [record.getMessage() for record in caplog.records if record.name == REPOSITORY_LOGGER]


def test_the_default_branch_is_downloaded_and_mirrored(github, tmp_path: Path) -> None:
    """The tarball path without a ref, the headers, the redirect followed, the folder mirrored"""
    stub, base_url = github
    (tmp_path / STALE_FILE).write_bytes(b'{}')

    report = sync_best_practice_repository(tmp_path, environ=ENVIRON, api_url=base_url)

    assert report == RepositorySyncReport(added=(FIRST_FILE,), removed=(STALE_FILE,))
    assert sorted(path.name for path in tmp_path.iterdir()) == [FIRST_FILE]
    assert (tmp_path / FIRST_FILE).read_bytes() == FIRST_CONTENT
    first, second = stub.received
    assert first['path'] == f'/repos/{REPOSITORY}/tarball'
    assert (first['headers']['Authorization'], first['headers']['Accept'],
            first['headers']['X-GitHub-Api-Version']) == (f'Bearer {TOKEN}', 'application/vnd.github+json',
                                                          '2022-11-28')
    assert second['path'] == f'{DOWNLOAD_PATH}?token={DOWNLOAD_TOKEN}'


def test_a_ref_is_the_last_path_segment(github, tmp_path: Path) -> None:
    """A branch with a slash"""
    stub, base_url = github

    sync_best_practice_repository(tmp_path, environ={**ENVIRON, BestPracticeRepositoryEnv.REF.value: 'release/1.0'},
                                  api_url=base_url)

    assert stub.received[0]['path'] == f'/repos/{REPOSITORY}/tarball/release/1.0'


@pytest.mark.parametrize('status', [401, 404])
def test_a_refusing_github_changes_nothing(github, tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                           status: int) -> None:
    """One WARNING naming the status, the folder as it was"""
    stub, base_url = github
    stub.status = status
    (tmp_path / STALE_FILE).write_bytes(b'{}')
    caplog.set_level(logging.INFO, logger=REPOSITORY_LOGGER)

    assert sync_best_practice_repository(tmp_path, environ=ENVIRON, api_url=base_url) is None

    assert [path.name for path in tmp_path.iterdir()] == [STALE_FILE]
    assert len(_messages(caplog)) == 1 and str(status) in _messages(caplog)[0]
    assert TOKEN not in _messages(caplog)[0]


def test_a_closed_port_changes_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """GitHub unreachable: one WARNING, no token in it"""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        closed_port: int = probe.getsockname()[1]
    caplog.set_level(logging.WARNING, logger=REPOSITORY_LOGGER)

    assert sync_best_practice_repository(tmp_path, environ=ENVIRON, api_url=f'http://{LOOPBACK}:{closed_port}') is None

    assert not list(tmp_path.iterdir())
    assert len(_messages(caplog)) == 1 and TOKEN not in _messages(caplog)[0]


def test_the_log_names_no_token(github, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """The token nowhere, not even at DEBUG; the redirect's token not in DataGerry's own lines

    urllib3 logs the URLs it requests at DEBUG, the redirect's query string with them - a library line, outside the sync
    """
    _stub, base_url = github
    caplog.set_level(logging.DEBUG)

    sync_best_practice_repository(tmp_path, environ=ENVIRON, api_url=base_url)

    assert TOKEN not in '\n'.join(record.getMessage() for record in caplog.records)
    assert DOWNLOAD_TOKEN not in '\n'.join(record.getMessage() for record in caplog.records
                                           if record.name.startswith('cmdb'))
