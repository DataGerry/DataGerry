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

A factory over a registry: `CmdbLog(**data)` returns an instance of the log class registered for the
data's `log_type`, falling back to `DEFAULT_LOG_TYPE` when that type cannot be resolved. The registry
holds exactly one entry today (`framework/constants.py` registers CmdbObjectLog under its own class
name), and every write path passes that name - so the fallback is the corrupt-data path, not a normal
one.

**Serialization deliberately lives on the log classes, not here.** A factory cannot serialize what it
does not know the shape of: a `to_json` on this class would hard-code one concrete log's field list and
silently misserialize any second registered type. Callers therefore use the chosen class's own
`from_data` / `to_json` (`CmdbObjectLog.to_json` in `LogsManager.insert_log`)
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

    Dynamically instantiates log objects based on their type and allows registration of custom log
    types. Serialization belongs to the log classes themselves - see the module docstring
    """
    REGISTERED_LOG_TYPE: dict[Any, Any] = {}
    DEFAULT_LOG_TYPE = CmdbObjectLog

    def __new__(cls, *args, **kwargs) -> Any:
        """
        Dynamically creates an instance of the appropriate log class based on provided arguments

        Only the keyword arguments select the class - the log type is read from `log_type`, which has
        no positional meaning here; positional arguments are passed on to the chosen class's
        constructor untouched.

        Note that every log class in this package derives from CmdbDAO, whose own `__new__` validates
        the REQUIRED_INIT_KEYS against the KEYWORD arguments alone - so a value passed positionally is
        refused there as a missing key. `*args` therefore only ever reaches a log class that does not
        inherit that validation

        Args:
            *args: Positional arguments for the log class constructor
            **kwargs: Keyword arguments, must include 'log_type' if a specific type is desired

        Returns:
            Instance of a log class derived from CmdbLog
        """
        return cls.__get_log_class(**kwargs)(*args, **kwargs)


    @classmethod
    def __get_log_class(cls, **kwargs) -> type:
        """
        Retrieves the registered log class for the given 'log_type'

        Defaults to DEFAULT_LOG_TYPE whenever the type cannot be resolved, which is every way a stored
        value can be unusable: absent (KeyError on the kwargs lookup), not registered (KeyError on the
        registry) or not even hashable (TypeError - a list or dict where a name belongs, which a
        hand-edited or half-migrated row can carry). Falling back is what keeps one corrupt row from
        taking down the whole log list

        Args:
            **kwargs: Should contain a 'log_type' key

        Returns:
            type: The log class associated with 'log_type'
        """
        try:
            log_class = cls.REGISTERED_LOG_TYPE[kwargs['log_type']]
        except (KeyError, TypeError):
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
