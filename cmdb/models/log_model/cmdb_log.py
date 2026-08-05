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
Implementation of CmdbLog
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CmdbLog - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbLog:
    """
    Factory and registry class for CMDB (Configuration Management Database) logs
    
    Dynamically instantiates log objects based on their type, 
    allows registration of custom log types, and provides 
    serialization methods for log instances.
    """
    REGISTERED_LOG_TYPE: dict[Any, Any] = {}
    DEFAULT_LOG_TYPE = CmdbObjectLog

    def __new__(cls, *args, **kwargs) -> Any:
        """
        Dynamically creates an instance of the appropriate log class 
        based on provided arguments

        Args:
            *args: Positional arguments for the log class constructor
            **kwargs: Keyword arguments, must include 'log_type' if a specific type is desired

        Returns:
            Instance of a log class derived from CmdbLog
        """
        return cls.__get_log_class(*args, **kwargs)(*args, **kwargs)


    @classmethod
    def __get_log_class(cls, **kwargs) -> type:
        """
        Retrieves the registered log class for the given 'log_type'. 
        Defaults to DEFAULT_LOG_TYPE if no matching type is found.

        Args:
            **kwargs: Should contain a 'log_type' key

        Returns:
            type: The log class associated with 'log_type'
        """
        try:
            log_class = cls.REGISTERED_LOG_TYPE[kwargs['log_type']]
        except (KeyError, ValueError):
            log_class = cls.DEFAULT_LOG_TYPE

        return log_class


    @classmethod
    def register_log_type(cls, log_name: str, log_class: Any) -> None:
        """
        Registers a new log type to the log factory

        Args:
            log_name (str): The name identifier for the new log type
            log_class (type): The log class corresponding to the log_name
        """
        cls.REGISTERED_LOG_TYPE[log_name] = log_class


    @classmethod
    def from_data(cls, data: dict, *args, **kwargs) -> "CmdbLog":
        """
        Instantiates a log object from a given data dictionary

        Args:
            data (dict): Data representing the log attributes. Should include 'log_type'
            *args: Additional positional arguments for the log class constructor
            **kwargs: Additional keyword arguments

        Returns:
            CmdbLog: An instance of the appropriate log class populated with data
        """
        return cls.__get_log_class(**data).from_data(data, *args, **kwargs)


    @classmethod
    def to_json(cls, instance: "CmdbLog") -> dict:
        """
        Serializes a log instance into a JSON-compatible dictionary

        Args:
            instance (CmdbLog): The log instance to serialize

        Returns:
            dict: Dictionary containing the log's serializable data
        """
        return {
            'public_id': instance.public_id,
            'log_time': instance.log_time,
            'log_type': instance.log_type,
            'action': instance.action,
            'object_id': instance.object_id,
            'version': instance.version,
            'user_name': instance.user_name,
            'user_id': instance.user_id,
            'render_state': instance.render_state,
            'changes': instance.changes,
            'comment': instance.comment,
            'action_name': instance.action_name
        }
