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
Helper functions for the DateSettings REST routes
"""
from typing import Any

from cmdb.settings.date_settings import DateSettingsDAO
# -------------------------------------------------------------------------------------------------------------------- #


def build_date_settings(data: dict[str, Any]) -> DateSettingsDAO:
    """
    Builds a DateSettingsDAO from a settings dictionary

    Only the recognised DateSettings fields are read, so persistence keys such as the MongoDB '_id'
    carried by a stored section (or any other extra keys) are ignored. Splatting a stored section
    directly into DateSettingsDAO would otherwise fail on the unexpected '_id' keyword.

    Args:
        data (dict[str, Any]): A mapping containing at least the 'date_format' and 'timezone' keys

    Returns:
        DateSettingsDAO: The constructed date settings data object
    """
    return DateSettingsDAO(
        date_format=data['date_format'],
        timezone=data['timezone'],
    )
