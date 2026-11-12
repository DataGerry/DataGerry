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
This module defines pytest fixtures for MongoDB connection and database management.
These fixtures provide necessary parameters and connections for testing purposes.
"""
import pytest

from cmdb.database import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.fixture(scope="session", name="mongodb_parameters")
def fixture_mongodb_parameters(request):
    """
    Retrieves MongoDB connection parameters from pytest command-line options
    
    Args:
        request (pytest.FixtureRequest): The pytest request object
    
    Returns:
        tuple: A tuple containing the MongoDB host, port, and database name
    """
    return request.config.getoption('--mongodb-host'), \
           request.config.getoption('--mongodb-port'), \
           request.config.getoption('--mongodb-database')


@pytest.fixture(scope="session")
def database_name(mongodb_parameters: tuple):
    """
    Provides the name of the test database
    
    Args:
        mongodb_parameters (tuple): MongoDB connection parameters
    
    Returns:
        str: The name of the MongoDB test database
    """
    return mongodb_parameters[2]


@pytest.fixture(scope="session")
def database_manager(mongodb_parameters: tuple):
    """
    Creates and returns a MongoDatabaseManager instance
    
    Args:
        mongodb_parameters (tuple): MongoDB connection parameters
    
    The session's one manager - every test reaches the database through it (``rest_api`` too); a test that needs
    the connector reads ``database_manager.connector``. The manager owns its connector and its keep-alive, so the
    session closes it at the end - ``close()`` stops the keep-alive first, so the client stays closed

    Yields:
        MongoDatabaseManager: An instance of MongoDatabaseManager configured for testing
    """
    host, port, database = mongodb_parameters
    manager = MongoDatabaseManager(host, port, database)

    yield manager

    manager.close()
