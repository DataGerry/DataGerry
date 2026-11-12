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
A second database manager for a test, closed when the test is done

A `MongoDatabaseManager` owns its connector and its client, so one a test builds next to the session's manager is a
second client - and, with the keep-alive on, a second thread. ``own_database_manager`` builds one without the
keep-alive (a test needs no idle ping) and closes it afterwards with ``close()``, so no pool or monitor thread
outlives the test
"""
from collections.abc import Iterator
from contextlib import contextmanager

from cmdb.database import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #


@contextmanager
def own_database_manager(host: str, port: int, database_name: str) -> Iterator[MongoDatabaseManager]:
    """
    A database manager of the test's own, without a keep-alive thread, its connector closed on the way out

    Args:
        host (str): MongoDB host
        port (int): MongoDB port
        database_name (str): The manager's default database

    Yields:
        MongoDatabaseManager: The manager, open for the block
    """
    manager = MongoDatabaseManager(host, port, database_name, start_keepalive=False)

    try:
        yield manager
    finally:
        manager.close()
