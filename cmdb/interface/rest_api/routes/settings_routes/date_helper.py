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
from cmdb.settings.date_settings_constants import DateSettingsKey
# -------------------------------------------------------------------------------------------------------------------- #


def build_date_settings(data: dict[str, Any]) -> DateSettingsDAO:
    """
    Builds a DateSettingsDAO from a settings dictionary

    Only the recognised DateSettings fields are read, so persistence keys such as the MongoDB '_id'
    carried by a stored section (or any other extra keys) are ignored. Splatting a stored section
    directly into DateSettingsDAO would otherwise fail on the unexpected '_id' keyword.

    A value that is missing, empty or not a string falls back to its default
    (``DateSettingsDAO.__DEFAULT_SETTINGS__``), one key at a time. The write's schema never lets such a value
    through, but a stored section the schema never saw - written before it, or by hand - is read on every page
    by the frontend's date pipe and must not turn that read into a 500

    Args:
        data (dict[str, Any]): A stored section or a validated request body

    Returns:
        DateSettingsDAO: The constructed date settings data object
    """
    return DateSettingsDAO(
        date_format=_setting_or_default(data, DateSettingsKey.DATE_FORMAT),
        timezone=_setting_or_default(data, DateSettingsKey.TIMEZONE),
    )


def _setting_or_default(data: dict[str, Any], key: DateSettingsKey) -> str:
    """
    Reads one date setting, or its default when the stored value is unusable

    Args:
        data (dict[str, Any]): A stored section or a validated request body
        key (DateSettingsKey): The setting to read

    Returns:
        str: The value when it is a non-empty string, otherwise the setting's default
    """
    value: Any = data.get(key)

    if isinstance(value, str) and value:
        return value

    return DateSettingsDAO.__DEFAULT_SETTINGS__[key]
