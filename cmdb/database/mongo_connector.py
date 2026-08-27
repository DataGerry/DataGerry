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
This module provides the `MongoConnector` class, the process-wide handle on a MongoDB connection

`MongoConnector` is a **singleton**: `__new__` caches the first instance on the class and returns it
for every later construction, while `__init__` still runs on that shared instance and refreshes its
attributes (including dropping the lazily-created `MongoClient`). The `MongoClient` itself is created
on first access to the `client` property rather than in the constructor, so a forked gunicorn worker
builds its own client instead of inheriting the parent's.

Two behaviours of this module are surprising and are recorded as open items rather than changed here:

* **TLS is decided by the connection string alone.** `__init__` drops the caller's deprecated `ssl`
  option **without carrying its value over** and sets `tls` solely from whether `CONNECTION_STRING`
  uses the `mongodb+srv://` scheme. A caller asking for `ssl=True` over a plain host/port therefore
  connects without TLS, and a `mongodb://…?tls=true` connection string has its TLS overridden to off
  by the injected keyword - see discussion-backlog #139. It also mutates the caller's options dict
  in place (#140).
* **A failed connection check raises rather than reporting a failure.** `connect()` converts every
  error into `DatabaseConnectionError`, so `is_connected()` returns True or raises but never returns
  False (#141), and the `@retry_operation` decorators on this class never actually retry, because the
  errors they catch are converted before they can escape (#142). `disconnect()` conversely swallows
  its failure and reports it as an ordinary disconnect (#143).

The singleton, its lifecycle and the `__new__` / `__init__` overlap are tracked as #144-#147.
"""
import os
from logging import Logger, getLogger
from typing import Any
from pymongo import MongoClient
from pymongo.database import Database

from cmdb.database.connection_status import ConnectionStatus
from cmdb.database.database_utils import retry_operation
from cmdb.database.database_constants import (
    MONGO_COMMAND_OK_KEY,
    MONGO_COMMAND_OK_VALUE,
    MONGO_CONNECTION_STRING_ENV,
    MONGO_HELLO_COMMAND,
    MONGO_SRV_SCHEME_PREFIX,
    MONGO_SSL_OPTION,
    MONGO_TLS_OPTION,
)

from cmdb.errors.database import DatabaseConnectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                MongoConnector - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class MongoConnector:
    """
    MongoConnector is managing the connection to a MongoDB database using PyMongo
    """
    _instance: "MongoConnector | None" = None # Singleton instance


    def __new__(cls, host: str, port: int, client_options: dict[str, Any] | None = None) -> "MongoConnector":
        """
        This method ensures that only one instance of MongoConnector is created.
        It will return the same instance every time.

        The instance is cached on the class regardless of the arguments, so a later construction with
        a different host/port returns the existing instance - whose attributes `__init__` then
        overwrites (see discussion-backlog #145). The attributes assigned here are assigned again by
        `__init__` on the same call; the overlap is tracked as #146

        Args:
            host (str): MongoDB host
            port (int): MongoDB port
            client_options (dict[str, Any] | None): MongoClient options

        Returns:
            MongoConnector: A singleton instance of MongoConnector
        """
        if not cls._instance:
            cls._instance = super().__new__(cls)

            # Initialize the instance with the provided arguments
            cls._instance.host = host
            cls._instance.port = int(port)
            cls._instance.client_options = client_options or {}
            cls._instance._client = None  # Lazy-loaded MongoClient

        return cls._instance


    def __init__(self, host: str, port: int, client_options: dict[str, Any] | None = None) -> None:
        """
        Initialises the attributes of the `MongoConnector` (the MongoClient itself is lazy-loaded)

        The TLS decision is made here: the deprecated `ssl` option is removed from the options and
        `tls` is set - unless the caller already supplied it - from the scheme of `CONNECTION_STRING`
        alone. The removed `ssl` value is NOT carried over, so `ssl=True` over a plain host/port ends
        up as `tls=False`, and a `mongodb://…?tls=true` connection string is overridden to off by the
        injected keyword; both are recorded as discussion-backlog #139

        Args:
            `host` (str): Host of the connection
            `port` (int): Port of the connection
            `client_options` (dict[str, Any] | None): Additional MongoClient options. Defaults to None.
                                                      **Stored and mutated by reference** - the caller's
                                                      dict loses its 'ssl' key and gains 'tls' (#140)

        Note:
            MongoConnector is a singleton, so __init__ runs on every constructor call and refreshes
            these attributes (including resetting the lazily-created client) for the shared instance.
            `MongoDatabaseManager.reset_connection` relies on that reset to drop a stale client (#147),
            and the dropped client is not closed first (#144)
        """
        self.connection_string: str | None = os.getenv(MONGO_CONNECTION_STRING_ENV)
        self.host: str = host
        self.port: int = int(port)
        self.client_options: dict[str, Any] = client_options or {}

        # TODO: improve handling of tls and ssl
        # Drop the deprecated 'ssl' option in favor of 'tls'
        self.client_options.pop(MONGO_SSL_OPTION, None)

        # Only set TLS here when it is not already configured via the connection string
        if MONGO_TLS_OPTION not in self.client_options:
            if self.connection_string and self.connection_string.startswith(MONGO_SRV_SCHEME_PREFIX):
                self.client_options[MONGO_TLS_OPTION] = True
            else:
                self.client_options[MONGO_TLS_OPTION] = False

        self._client = None  # Lazy-loaded MongoClient


    @property
    def client(self) -> MongoClient:
        """
        Returns the MongoClient, creating it on first access

        The client is lazy-loaded to prevent pre-fork initialization issues (a forked worker must
        create its own client rather than inherit one from the parent process). A `CONNECTION_STRING`
        replaces the host/port pair; without one the client is built with `connect=False`, so no I/O
        happens here either way

        Raises:
            DatabaseConnectionError: If the MongoClient could not be initialised. The original error is
                                     chained and logged - the raised message itself is generic, so a
                                     pymongo option conflict is only identifiable from the log

        Returns:
            MongoClient: The (cached) MongoDB client
        """
        if self._client is None:
            try:
                if self.connection_string:
                    self._client = MongoClient(self.connection_string, **self.client_options)
                else:
                    self._client = MongoClient(host=self.host, port=self.port, connect=False, **self.client_options)
            except Exception as err:
                LOGGER.error(
                    "Failed to initialize MongoClient. Exception: %s. Type: %s",
                    err, type(err).__name__, exc_info=True,
                )
                raise DatabaseConnectionError("Failed to initialize MongoDB connection.") from err

        return self._client

# -------------------------------------------------------------------------------------------------------------------- #

    @retry_operation
    def get_database(self, db_name: str) -> Database[Any]:
        """
        Retrieves database from client

        A purely local lookup on the client - no I/O, so the `retry_operation` wrapper never has a
        retryable error to act on (see discussion-backlog #142)

        Args:
            db_name (str): name of Database

        Raises:
            DatabaseConnectionError: If the underlying MongoClient could not be initialised

        Returns:
            Database[Any]: The database with the given name
        """
        return self.client.get_database(db_name)


    @retry_operation
    def connect(self) -> ConnectionStatus:
        """
        Checks if database is reachable

        Runs the 'hello' command against the admin database. **Every failure is raised, never
        reported**: a returned ConnectionStatus is always `connected=True`, and an unreachable server,
        an unacknowledged response and a client that cannot be built all surface as
        DatabaseConnectionError. Callers wanting a boolean therefore have to catch (see
        discussion-backlog #141). Because the raised error is not a pymongo error, the
        `retry_operation` wrapper never retries the probe either (#142)

        Raises:
            DatabaseConnectionError: If the database connection check fails, if the server does not
                                     acknowledge the command, or if the client could not be initialised

        Returns:
            ConnectionStatus: Always a connected status - a disconnected one is never returned
        """
        try:
            response: dict[str, Any] = self.client.admin.command(MONGO_HELLO_COMMAND)

            if response.get(MONGO_COMMAND_OK_KEY) == MONGO_COMMAND_OK_VALUE:
                return ConnectionStatus(connected=True, message=str(response))

            raise DatabaseConnectionError("Unexpected response from database: " + str(response))
        except Exception as err:
            raise DatabaseConnectionError(str(err)) from err


    @retry_operation
    def disconnect(self) -> ConnectionStatus:
        """
        Closes the connection to the database

        **A failure is swallowed, not raised**: closing a broken client returns the same
        `connected=False` status a successful close does - only the message differs - and the failed
        client is left in place, so the next `client` access hands back that same broken object
        instead of building a new one (see discussion-backlog #143). Note the manager's keep-alive
        thread re-creates the client within its ping interval, so a disconnect does not stay closed
        (#148)

        Returns:
            ConnectionStatus: Always a disconnected status; the message distinguishes a close, a
                              no-op when no client existed, and a failed close
        """
        try:
            if self._client:
                self._client.close()
                self._client = None

                return ConnectionStatus(connected=False, message="Successfully disconnected from the database.")

            return ConnectionStatus(connected=False, message="No active database connection to close.")
        except Exception as err:
            return ConnectionStatus(connected=False, message=f"Error while disconnecting: {err}")


    @retry_operation
    def is_connected(self) -> bool:
        """
        Checks the current connection status to the database

        Delegates to `connect`, which raises on every failure, so this returns True or raises - it
        **never returns False** (see discussion-backlog #141). `MongoDatabaseManager.status` and the
        `GET /rest/` connection check inherit that, which is why an unreachable database surfaces
        there as a 500 rather than as `connected: false`

        Raises:
            DatabaseConnectionError: If the database is unreachable or the client cannot be built

        Returns:
            bool: True when the database answered the probe
        """
        return self.connect().get_status()
