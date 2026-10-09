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
Validation schema for DateSettingsDAO

DateSettingsDAO holds the instance's regional date settings - the date format and the timezone every date in
the frontend is rendered with. It is stored as one document (`_id` 'date') of the settings collection; in cloud
mode each tenant has its own.

This module is the single source of the request schema of ``POST|PUT /date/``, consumed as DateSettingsDAO.SCHEMA.

**Both values are checked for shape only.** They are a moment.js format string and a moment-timezone name, and
only the frontend interprets them - the backend never formats a date with them. Python's ``zoneinfo`` list is not
moment's list, so checking the name against it could refuse a timezone the frontend itself offers. A missing,
empty or non-string value is refused: it would reach the date pipe of every page.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
def get_date_settings_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a DateSettingsDAO document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as DateSettingsDAO.SCHEMA
    """
    # Imported inside the builder, as every class_schema builder names its model's constants: the DAO imports
    # this module for its SCHEMA, so a module-level import of the settings package could close a cycle
    # pylint: disable=import-outside-toplevel
    from cmdb.settings.date_settings_constants import (
        DATE_FORMAT_MAX_LENGTH,
        TIMEZONE_MAX_LENGTH,
        DateSettingsKey,
    )

    return {
        # The moment.js format every date is rendered with, e.g. 'YYYY-MM-DDTHH:mm'
        DateSettingsKey.DATE_FORMAT.value: {
            'type': 'string',
            'required': True,
            'empty': False,
            'maxlength': DATE_FORMAT_MAX_LENGTH,
        },
        # The moment-timezone name dates are shown in, e.g. 'Europe/Berlin'
        DateSettingsKey.TIMEZONE.value: {
            'type': 'string',
            'required': True,
            'empty': False,
            'maxlength': TIMEZONE_MAX_LENGTH,
        },
    }
