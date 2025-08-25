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
Implementation of CmdbDAO
"""
import logging
from typing import Type, TypeVar, Any
import pprint
from pymongo import IndexModel

from cmdb.models.cmdb_versioning import Versioning

from cmdb.errors.cmdb_object import NoPublicIDError, NoVersionError, RequiredInitKeyNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

T = TypeVar("T", bound="CmdbDAO")

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CmdbDAO - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbDAO:
    """
    The data access object is the basic presentation if objects and their necessary dependent classes are to be stored
    in the database

    Attributes:
        DAO_ASCENDING (int): models sort order ascending
        DAO_DESCENDING (int): models sort order descending
        COLLECTION (str): name of the database table - should always be overwritten
        IGNORED_INIT_KEYS (list, optional): list of default init keys which an specific object won't need
        REQUIRED_INIT_KEYS (list, optional): list of default parameters which an object needs to work
        VERSIONING_MAJOR (int): addend for major version updates
        VERSIONING_MINOR (int): addend for minor version updates
        VERSIONING_PATCH (int): addend for small patches

    Note:
        COLLECTION and REQUIRED_INIT_KEYS should always be overwritten by inherited classes
    """

    DAO_ASCENDING = 1
    DAO_DESCENDING = -1
    COLLECTION = 'framework.*'
    MODEL: str = ''
    SCHEMA: dict[str, Any] = {}

    __SUPER_INIT_KEYS: list[str] = [
        'public_id'
    ]

    SUPER_INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [('public_id', DAO_ASCENDING)],
            'name': 'public_id',
            'unique': True
        }
    ]

    IGNORED_INIT_KEYS = []
    REQUIRED_INIT_KEYS = []
    INDEX_KEYS = []
    VERSIONING_MAJOR = 2
    VERSIONING_MINOR = 1
    VERSIONING_PATCH = 0


    def __init__(self, public_id : int, **kwargs: Any) -> None:
        """
        All parameters inside *kwargs will be auto convert to attributes

        Args:
            **kwargs: list of parameters
        """
        self.public_id: int = int(public_id)

        for key, value in kwargs.items():
            if key == 'version':
                self.version = value
            else:
                setattr(self, key, value)


    def get_public_id(self) -> int:
        """
        get the public id of current element

        Note:
            Since the models object is not initializable
            the child class object will inherit this function
            SHOULD NOT BE OVERWRITTEN!

        Raises:
            NoPublicIDError: if `public_id` is zero or not set

        Returns:
            int: public id
        """
        if self.public_id == 0:
            raise NoPublicIDError("No public_id assigned!")

        return self.public_id


    def __new__(cls, *args: Any, **kwargs: Any):
        """
        auto call function by object initialization
        checks if all required keys for cmdb usage are present
        @deprecated_implementation
        if not all(key in key_list for key in cls.REQUIRED_INIT_KEYS):

        Returns:
            Instance of the object

        Raises:
            RequiredInitKeyNotFoundError: if some given attributes are not inside the requirement lists
        """
        init_keys = cls.__SUPER_INIT_KEYS + cls.REQUIRED_INIT_KEYS

        if len(cls.IGNORED_INIT_KEYS) > 0:
            init_keys = [i for j, i in enumerate(init_keys) if j in cls.IGNORED_INIT_KEYS]

        for req_key in init_keys:
            if req_key in kwargs:
                continue

            raise RequiredInitKeyNotFoundError(f"A required InitKey is missing: {req_key}!")

        return super().__new__(cls)


    @classmethod
    def get_index_keys(cls):
        """
        Retrieves a list of index models based on class-defined index keys

        Returns:
            list: A list of IndexModel instances created from `INDEX_KEYS` and `SUPER_INDEX_KEYS`
        """
        return [IndexModel(**index) for index in cls.INDEX_KEYS + cls.SUPER_INDEX_KEYS]


    def update_version(self, update) -> str:
        """
        Update the version number of the object

        Args:
            update (int): update step

        Returns:
            new version number

        Raises:
            NoVersionError: if object has no version control
            TypeError: if version is not a float
        """
        if not hasattr(self, 'version') or self.version is None:
            raise NoVersionError(f"The object (ID: {self.get_public_id()}) has no version property")

        updater_version = Versioning(*map(int, self.version.split('.')))

        if not isinstance(updater_version, Versioning):
            raise TypeError('Version type must be a Versioning')

        if update == self.VERSIONING_MAJOR:
            updater_version.update_major()
        elif update == self.VERSIONING_MINOR:
            updater_version.update_minor()
        else:
            updater_version.update_patch()

        return repr(updater_version)


    def get_version(self) -> str:
        """
        Get version number if exists
        Returns:
            version number

        Raiser:
            NoVersionError: If not self.version
        """
        if self.version:
            return self.version

        raise NoVersionError(f"The object (ID: {self.get_public_id()}) has no version property")


    def __repr__(self):
        return f'Class: {self.__class__.__name__} \nDict:\n{pprint.pformat(self.__dict__)}'


    @classmethod
    def from_data(cls: Type[T], data: dict[str, Any]) -> T:
        """
        Each subclass must implement this to initialize from a dictionary
        """
        raise NotImplementedError(f"{cls.__name__} must implement a 'from_data' method!")


    @classmethod
    def to_json(cls, instance: T) -> dict[str, Any]:
        """
        Each subclass must implement this to convert to a JSON-compatible dict
        """
        raise NotImplementedError(f"{cls.__name__} must implement a 'to_json' method!")
