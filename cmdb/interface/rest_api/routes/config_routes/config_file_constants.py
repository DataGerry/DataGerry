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
Constants consumed by the config-file status routes

Gathers the response keys that are *not* config-file keys. The per-setting flags of the
OpenCelium status response are named by `cmdb.open_celium.oc_constants.OcConfigKey`, so the
response shape stays tied to the config section it reports on
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class OcConfigStatusKey(BaseStrEnum):
    """
    Keys of the `GET /config_file/status/opencelium` response that are not config-file keys

    The remaining keys of that response are the `[OpenCelium]` setting names themselves - one
    boolean per `OcConfigKey` member - so the two together describe the full frontend contract

    Attributes:
        STATUS: True only when every `OcConfigKey` setting is usable, i.e. OpenCelium is ready
        SECTION: False when the `[OpenCelium]` section is missing entirely (or no config file is
            loaded at all), True when it exists - even if it is incompletely filled
    """
    STATUS = 'status'
    SECTION = 'section'


# Smallest port number accepted as a configured OpenCelium port; 0 and negatives are unusable
MIN_VALID_PORT: int = 1
