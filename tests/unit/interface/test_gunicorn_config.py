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
Unit tests for cmdb.interface.gunicorn_config.post_fork

The gunicorn ``post_fork`` hook resets a forked worker's MongoDB connection, and leaves a worker whose
application carries no database manager alone. Gunicorn calls it positionally with the arbiter and the
worker, so the arbiter parameter's name is free - the tests call it the way gunicorn does
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from cmdb.interface.gunicorn_config import post_fork
# -------------------------------------------------------------------------------------------------------------------- #

def _worker(application: object) -> SimpleNamespace:
    """A gunicorn worker whose app wraps ``application``."""
    return SimpleNamespace(app=SimpleNamespace(application=application))


def test_post_fork_resets_the_workers_database_connection() -> None:
    """A forked worker must not keep the MongoClient it inherited from the arbiter."""
    database_manager = MagicMock()

    post_fork(MagicMock(), _worker(SimpleNamespace(database_manager=database_manager)))

    database_manager.reset_connection.assert_called_once_with()


def test_post_fork_leaves_an_application_without_a_database_manager_alone() -> None:
    """The docs and SPA apps carry no database manager, and a missing one must not raise."""
    post_fork(MagicMock(), _worker(SimpleNamespace()))


def test_post_fork_tolerates_a_worker_without_an_app() -> None:
    """A worker that has not loaded its app yet is left as it is."""
    post_fork(MagicMock(), SimpleNamespace())


def test_post_fork_never_reads_the_arbiter() -> None:
    """Only the worker drives the hook - the arbiter is accepted because gunicorn passes it."""
    arbiter = MagicMock()

    post_fork(arbiter, _worker(SimpleNamespace(database_manager=MagicMock())))

    assert not arbiter.mock_calls
