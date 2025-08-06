# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
This module provides the `MongoConnector` class to establish and manage a connection 
to a MongoDB database
"""
import os
import logging
from pymongo import MongoClient
from pymongo.database import Database

from cmdb.database.connection_status import ConnectionStatus
from cmdb.database.database_utils import retry_operation

from cmdb.errors.database import DatabaseConnectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                MongoConnector - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class MongoConnector:
    """
    MongoConnector is managing the connection to a MongoDB database using PyMongo
    """
    _instance = None # Singleton instance


    # def __new__(cls, host: str, port: int, database_name: str, client_options: dict = None):
    def __new__(cls, host: str, port: int, client_options: dict = None):
        """
        This method ensures that only one instance of MongoConnector is created.
        It will return the same instance every time.

        Args:
            host (str): MongoDB host.
            port (int): MongoDB port.
            database_name (str): Database name.
            client_options (dict): MongoClient options.

        Returns:
            MongoConnector: A singleton instance of MongoConnector.
        """
        if not cls._instance:
            cls._instance = super(MongoConnector, cls).__new__(cls)

            # Initialize the instance with the provided arguments
            cls._instance.host = host
            cls._instance.port = int(port)
            # cls._instance.database_name = database_name
            cls._instance.client_options = client_options or {}
            cls._instance._client = None  # Lazy-loaded MongoClient
            # cls._instance._database = None  # Lazy-loaded Database reference

        return cls._instance

    # def __init__(self, host: str, port: int, database_name: str, client_options: dict = None):
    def __init__(self, host: str, port: int, client_options: dict = None):
        """
        Initialises the connection to MongoDB and the attributes of the `MongoConnector`

        Args:
            `host` (str): Host of the connection
            `port` (int): Port of the connection
            `database_name` (str): Name of the database
            `client_options` (dict, optional): Additional client options. Defaults to None.

        Raises:
            `DatabaseConnectionError`: When the connection initialisation failed
        """
        self.connection_string = os.getenv('CONNECTION_STRING')
        self.host = host
        self.port = int(port)
        # self.database_name = database_name
        self.client_options = client_options or {}
        self._client = None  # Lazy-loaded MongoClient
        # self._database = None  # Lazy-loaded Database reference


    @property
    def client(self):
        """
        Lazy-loads MongoClient to prevent pre-fork initialization issues
        """
        if self._client is None:
            try:
                if self.connection_string:
                    self._client = MongoClient(self.connection_string, **self.client_options)
                else:
                    self._client = MongoClient(host=self.host, port=self.port, connect=False, **self.client_options)
            except Exception as err:
                LOGGER.error("Failed to initialize MongoClient. Exception: %s. Type: %s", err, type(err), exc_info=True)
                raise DatabaseConnectionError("Failed to initialize MongoDB connection.") from err
        return self._client

# -------------------------------------------------------------------------------------------------------------------- #

    @retry_operation
    def get_database(self, db_name: str) -> Database:
        """
        Retrieves database from client

        Args:
            db_name (str): name of Database

        Returns:
            Database: The database with the given name
        """
        return self.client.get_database(db_name)


    @retry_operation
    def connect(self) -> ConnectionStatus:
        """
        Checks if database is reachable

        Raises:
            DatabaseConnectionError: If the database connection check fails

        Returns:
            ConnectionStatus: The current connection status, indicating success or failure
        """
        try:
            response = self.client.admin.command('hello')
            if response.get("ok") == 1:
                return ConnectionStatus(connected=True, message=str(response))

            raise DatabaseConnectionError("Unexpected response from database: " + str(response))
        except Exception as err:
            raise DatabaseConnectionError(err) from err


    @retry_operation
    def disconnect(self) -> ConnectionStatus:
        """
        Closes the connection to the database

        Returns:
            ConnectionStatus: The status indicating the disconnection result
        """
        try:
            if self._client:
                self._client.close()
                self._client = None
                # self._database = None
                return ConnectionStatus(connected=False, message="Successfully disconnected from the database.")

            return ConnectionStatus(connected=False, message="No active database connection to close.")
        except Exception as err:
            return ConnectionStatus(connected=False, message=f"Error while disconnecting: {err}")


    @retry_operation
    def is_connected(self) -> bool:
        """
        Checks the current connection status to the database
        
        Returns:
            bool: True if successfully connected to the database, False otherwise
        """
        return self.connect().get_status()
