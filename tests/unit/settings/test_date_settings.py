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
Unit tests for DateSettingsDAO

The DAO declares its own wire shape, so the JSON encoder serialises it through ``to_json()`` and never
falls back to the instance's attribute dump
"""
import json
import logging

from cmdb.database import json_codec
from cmdb.settings.date_settings import DateSettingsDAO
# -------------------------------------------------------------------------------------------------------------------- #

DATE_FORMAT: str = 'DD.MM.YYYY'
TIMEZONE: str = 'Europe/Berlin'
DATE_SECTION_ID: str = 'date'
DICT_FALLBACK_MESSAGE: str = 'through its __dict__'


def test_to_json_answers_the_three_settings_keys() -> None:
    """to_json answers the section id, the date format and the timezone - and nothing else"""
    dao = DateSettingsDAO(date_format=DATE_FORMAT, timezone=TIMEZONE)

    assert dao.to_json() == {'_id': DATE_SECTION_ID, 'date_format': DATE_FORMAT, 'timezone': TIMEZONE}


def test_the_encoder_uses_to_json_instead_of_the_dict_fallback(caplog) -> None:
    """json.dumps with the codec hook serialises the DAO through to_json, without the __dict__ debug line"""
    dao = DateSettingsDAO(date_format=DATE_FORMAT, timezone=TIMEZONE)

    with caplog.at_level(logging.DEBUG, logger=json_codec.__name__):
        encoded: str = json.dumps(dao, default=json_codec.default)

    assert json.loads(encoded) == dao.to_json()
    assert DICT_FALLBACK_MESSAGE not in caplog.text
