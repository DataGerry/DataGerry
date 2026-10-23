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
Assembles a configuration export: the database version it is stamped with and one section per component

The version is read strictly. The system page reports an unreadable version as 0 and carries on; an export stamped
with a version that is not the database's could never be imported anywhere, so here a missing or malformed version
is an answer of its own (None) that the route refuses
"""
from typing import Any, Sequence

from cmdb.manager import SettingsManager
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.framework.configuration_transfer.transfer_component import TransferComponent
from cmdb.framework.configuration_transfer.transfer_file import build_transfer_file, is_strict_int
# -------------------------------------------------------------------------------------------------------------------- #

def read_database_version(settings_manager: SettingsManager) -> int | None:
    """
    Reads the updater version the database records, strictly

    Args:
        settings_manager (SettingsManager): The tenant's settings manager

    Raises:
        DocumentGetError: When the settings could not be read

    Returns:
        int | None: The version, or None when none is recorded or it is not a positive whole number
    """
    section: dict[str, Any] | None = settings_manager.get_section(UpdaterSetting.SECTION.value)
    version: Any = (section or {}).get(UpdaterSetting.VERSION.value)

    return version if is_strict_int(version) and version > 0 else None


def export_configuration(components: Sequence[TransferComponent], db_version: int, name: str,
                         description: str = '') -> dict[str, Any]:
    """
    Builds the transfer file of a configuration: one section per component, in the order given

    Args:
        components (Sequence[TransferComponent]): The components, built on the tenant's managers
        db_version (int): The updater version of the exporting database
        name (str): What the exporting user calls the file
        description (str): The exporting user's description of it - empty when none was given

    Raises:
        BaseManagerGetError: When a component's counter or documents could not be read

    Returns:
        dict[str, Any]: The transfer file
    """
    return build_transfer_file(db_version, {component.NAME.value: component.export_section()
                                            for component in components},
                               name=name, description=description)
