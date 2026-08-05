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
This module contains all Database error classes
"""
# -------------------------------------------------------------------------------------------------------------------- #

class DataBaseError(Exception):
    """
    Raised to catch all Database related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all Database related errors
        """
        super().__init__(err)

# ------------------------------------------------- DATABASE - ERRORS ------------------------------------------------ #

class DatabaseConnectionError(DataBaseError):
    """
    Error if connection to database broke up or unable to connect
    """


class ServerTimeoutError(DataBaseError):
    """
    Server timeout error if connection is lost
    """


class DatabaseAlreadyExistsError(DataBaseError):
    """
    Error when database already exists
    """


class DatabaseNotFoundError(DataBaseError):
    """
    Error when database does not exist
    """


class SetDatabaseError(DataBaseError):
    """
    Error if database could not be set for a connector
    """


class CollectionAlreadyExistsError(DataBaseError):
    """
    Raised when trying to create a collection that alrady exists
    """


class GetCollectionError(DataBaseError):
    """
    Raised when a collection could not be retrieved
    """


class DeleteCollectionError(DataBaseError):
    """
    Raised when a collection could not be deleted
    """


class CreateIndexesError(DataBaseError):
    """
    Raised when indexes for a collection could not be created
    """


class GetIndexesError(DataBaseError):
    """
    Raised when indexes for a collection could not be retrieved
    """


class NoDocumentFoundError(DataBaseError):
    """
    Error if no document was found
    """


class DocumentInsertError(DataBaseError):
    """
    Raised if a document could not be created in a collection
    """


class DocumentUpdateError(DataBaseError):
    """
    Raised if a document could not be updated in a collection
    """


class DocumentDeleteError(DataBaseError):
    """
    Raised if a document could not be deleted from a collection
    """


class DocumentGetError(DataBaseError):
    """
    Raised if a document could not be retrieved from a collection
    """


class DocumentAggregationError(DataBaseError):
    """
    Raised if an aggregation operation fails
    """


class PublicIdCounterInitError(DataBaseError):
    """
    Raised if a public_id counter could not be initialised
    """


class CollectionInitError(DataBaseError):
    """
    Raised when a collection could not be initialised
    """


class DocumentLockTimeoutError(DataBaseError):
    """
    Raised when a MongoDB LockTimeout occurs
    """


class DocumentNetworkError(DataBaseError):
    """
    Raised when an insert fails due to network or timeout issues
    """
