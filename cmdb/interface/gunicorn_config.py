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
Implementation of Gunicorn post fork method
"""
from logging import Logger, getLogger
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def post_fork(_server: Any, worker: Any) -> None:
    """
    Ensures MongoDB connections are properly reinitialized after forking

    Gunicorn's ``post_fork`` server hook: gunicorn calls it in each new worker, positionally, with the
    arbiter and the worker. Only the worker is read, which is why the arbiter is ``_server``. A worker
    whose application carries no ``database_manager`` (the docs or SPA app) is left alone

    Args:
        _server (Any): The gunicorn arbiter that forked the worker
        worker (Any): The forked gunicorn worker
    """
    if hasattr(worker, 'app') and\
       hasattr(worker.app, 'application') and\
       hasattr(worker.app.application, 'database_manager'):
        # Access the `database_manager` and reset the connection
        worker.app.application.database_manager.reset_connection()
