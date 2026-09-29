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
Constants of the DateSettings section

The section is stored as one document of the settings collection. Its id and document keys are
persisted and are also the wire keys of the /date/ routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'DATE_SETTINGS_SECTION',
    'DateSettingsKey',
]

# The '_id' of the settings document holding the date settings
DATE_SETTINGS_SECTION: str = 'date'


class DateSettingsKey(BaseStrEnum):
    """Document keys of the stored DateSettings section"""
    ID = '_id'
    DATE_FORMAT = 'date_format'
    TIMEZONE = 'timezone'
