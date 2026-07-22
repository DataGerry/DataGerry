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
Unit tests for build_date_settings (date_helper).

The helper turns a settings dictionary into a DateSettingsDAO while ignoring persistence keys such
as the stored MongoDB '_id'. This is the fix for the crash where a stored 'date' section (which
carries '_id') could not be splatted back into DateSettingsDAO.
"""
import pytest

from cmdb.settings.date_settings import DateSettingsDAO
from cmdb.interface.rest_api.routes.settings_routes.date_helper import build_date_settings
# -------------------------------------------------------------------------------------------------------------------- #

DATE_FORMAT: str = 'DD.MM.YYYY'
TIMEZONE: str = 'Europe/Berlin'


def test_builds_dao_from_plain_dict() -> None:
    """A dict with exactly the recognised keys yields a DateSettingsDAO with those values."""
    dao = build_date_settings({'date_format': DATE_FORMAT, 'timezone': TIMEZONE})

    assert isinstance(dao, DateSettingsDAO)
    assert dao.date_format == DATE_FORMAT
    assert dao.timezone == TIMEZONE


def test_ignores_stored_id_key() -> None:
    """A stored section carrying '_id' is accepted (regression: previously raised TypeError)."""
    stored_section = {'_id': 'date', 'date_format': DATE_FORMAT, 'timezone': TIMEZONE}

    dao = build_date_settings(stored_section)

    assert dao.date_format == DATE_FORMAT
    assert dao.timezone == TIMEZONE


def test_ignores_unknown_extra_keys() -> None:
    """Extra keys beyond the recognised fields are ignored rather than raising."""
    dao = build_date_settings({
        'date_format': DATE_FORMAT,
        'timezone': TIMEZONE,
        'unexpected': 'value',
    })

    assert dao.date_format == DATE_FORMAT
    assert dao.timezone == TIMEZONE


def test_default_settings_round_trip() -> None:
    """The DAO defaults are a valid input for the helper."""
    dao = build_date_settings(DateSettingsDAO.__DEFAULT_SETTINGS__)

    assert dao.date_format == DateSettingsDAO.__DEFAULT_SETTINGS__['date_format']
    assert dao.timezone == DateSettingsDAO.__DEFAULT_SETTINGS__['timezone']


@pytest.mark.parametrize('missing_key', ['date_format', 'timezone'])
def test_missing_required_key_raises_key_error(missing_key: str) -> None:
    """A missing required field raises KeyError (schema-level 400 handling is tracked separately)."""
    data = {'date_format': DATE_FORMAT, 'timezone': TIMEZONE}
    data.pop(missing_key)

    with pytest.raises(KeyError):
        build_date_settings(data)
