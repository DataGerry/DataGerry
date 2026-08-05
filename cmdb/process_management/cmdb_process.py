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
Service-registration value object consumed by `ProcessManager`

Each `CmdbProcess` is a `(name, class_path)` pair describing one of the long-running services
DataGerry should spawn at startup. The full list of definitions lives in
`ProcessManager._initialize_service_definitions`; at spawn time `ProcessManager` reads each
entry's class path, resolves it via `cmdb.utils.helpers.load_class`, and starts a dedicated
`multiprocessing.Process` for it. The `name` field also flows into the daemon log filename
(`<name>.log`) produced by `cmdb.utils.logger.get_logging_conf`
"""
from dataclasses import dataclass
# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbProcess - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CmdbProcess:
    """
    Service-registration record: a process name plus the fully-qualified class to spawn

    Immutable value object created once per service in
    `ProcessManager._initialize_service_definitions` and read back during the spawn loop to
    drive the dynamic import. `frozen=True` makes the dataclass hashable and rejects in-place
    mutation, so two `CmdbProcess` entries with identical `(name, class_path)` compare equal
    and can be used as dict / set keys

    Attributes:
        name (str): Process name; surfaces as the `multiprocessing.Process` name (which
            `cmdb.utils.logger.get_logging_conf` uses to derive the daemon log filename
            `<name>.log`) and as the lookup key inside `ProcessManager`
        class_path (str): Fully-qualified import path of the service class
            (e.g. `cmdb.interface.gunicorn.WebCmdbService`); resolved at spawn time by
            `cmdb.utils.helpers.load_class`, which requires at least one dot in the path
    """
    name: str
    class_path: str
