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
Process-wide singleton accessor for the DataGerry config-file reader

Provides `SystemConfigReader`, a thin wrapper that exposes *the* `ConfigFileReader` for the
running process. The bootstrap in `cmdb.__main__._init_system_config_reader` mutates the
class-level `RUNNING_CONFIG_NAME` / `RUNNING_CONFIG_LOCATION` when the CLI `-c` flag points
at a non-default config path, then calls `SystemConfigReader(name, location)` once. Every
subsequent `SystemConfigReader()` call across the codebase (database updaters, gunicorn
bootstrap, REST init, OpenCelium / ChatGPT connectors, etc.) returns the same cached
`ConfigFileReader` and ignores any args passed
"""
import os

from cmdb.manager.system_manager.config_file_reader import ConfigFileReader
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                              SystemConfigReader - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
# TDOD: Rework/Refactor SystemConfigReader and ConfigFileReader
class SystemConfigReader:
    """
    Singleton accessor for the process-wide `ConfigFileReader`

    On first call constructs a `ConfigFileReader` from `(config_name, config_location)` and
    caches it on the class as `SystemConfigReader.instance`; every later call returns that
    same instance regardless of arguments, so the reader cannot be re-pointed at a different
    file once initialised. Implemented by having `__new__` return a `ConfigFileReader`
    directly (not a `SystemConfigReader`) — so the wrapper class itself is never instantiated,
    `__init__` is bypassed, and all subsequent attribute access happens on the underlying
    `ConfigFileReader`. Values served by the reader fall back to matching environment
    variables when defined, via `SystemEnvironmentReader`

    Class attributes:
        DEFAULT_CONFIG_LOCATION (str): Source-relative fallback directory holding cmdb.conf
            (`cmdb/etc/`). In a frozen / installed build this resolves relative to the
            installed module, so the CLI `-c` flag is the supported way to point at a real
            config in production
        DEFAULT_CONFIG_NAME (str): Default config filename (`cmdb.conf`)
        RUNNING_CONFIG_LOCATION (str): Directory the singleton is currently bound to;
            mutated by the bootstrap before first instantiation
        RUNNING_CONFIG_NAME (str): Filename the singleton is currently bound to; mutated by
            the bootstrap before first instantiation
        CONFIG_LOADED / CONFIG_NOT_LOADED (bool): Status sentinels mirrored from
            `ConfigFileReader`; unused on this class but kept for API symmetry
        instance (ConfigFileReader | None): The cached reader; `None` until the first call
    """
    DEFAULT_CONFIG_LOCATION = os.path.join(os.path.dirname(__file__), '../../etc/')
    DEFAULT_CONFIG_NAME = 'cmdb.conf'
    RUNNING_CONFIG_LOCATION = DEFAULT_CONFIG_LOCATION
    RUNNING_CONFIG_NAME = DEFAULT_CONFIG_NAME
    CONFIG_LOADED = True
    CONFIG_NOT_LOADED = False
    instance = None


    def __new__(cls, config_name: str | None = None, config_location=None) -> ConfigFileReader:
        """
        Returns the cached `ConfigFileReader`, constructing it on the first call

        Departs from the normal `cls`-returning `__new__` contract: returns a
        `ConfigFileReader` directly so callers immediately get the underlying reader and the
        wrapper class is never actually instantiated. After the first call the cached
        instance is returned regardless of arguments — passing different
        `(config_name, config_location)` to a later call does *not* reload the config. The
        supported bootstrap pattern is to mutate `RUNNING_CONFIG_NAME` /
        `RUNNING_CONFIG_LOCATION` before this method runs for the first time (see
        `cmdb.__main__._init_system_config_reader`)

        Args:
            config_name (str | None): Config filename including extension; `None` puts the
                underlying reader into config-file-less mode (env vars only)
            config_location (str | None): Directory containing the config file; ignored when
                `config_name` is `None`

        Returns:
            ConfigFileReader: The process-wide reader (annotation reflects the runtime type)
        """
        if not SystemConfigReader.instance:
            SystemConfigReader.instance = ConfigFileReader(config_name, config_location)

        return SystemConfigReader.instance


    def __getattr__(self, name):
        """
        Delegates attribute reads to the cached `ConfigFileReader`

        Note: unreachable in practice — `__new__` returns a `ConfigFileReader` directly, so no
        `SystemConfigReader` instance ever exists for Python to invoke this on

        Args:
            name (str): Attribute name being looked up

        Returns:
            Any: The attribute value as exposed by the underlying `ConfigFileReader`
        """
        return getattr(self.instance, name)


    def __setattr__(self, name, value) -> None:
        """
        Delegates attribute writes to the cached `ConfigFileReader`

        Note: unreachable in practice — `__new__` returns a `ConfigFileReader` directly, so no
        `SystemConfigReader` instance ever exists for Python to invoke this on

        Args:
            name (str): Attribute name being assigned
            value (Any): Value to assign on the underlying `ConfigFileReader`
        """
        return setattr(self.instance, name, value)
