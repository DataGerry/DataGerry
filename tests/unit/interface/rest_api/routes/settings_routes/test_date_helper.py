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
as the stored MongoDB '_id', so a stored 'date' section (which carries '_id') can be splatted back
into DateSettingsDAO. A missing or unusable value is read as its default, one key at a time.
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
    """A stored section carrying '_id' is accepted rather than raising TypeError."""
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
def test_a_missing_key_falls_back_to_its_default(missing_key: str) -> None:
    """A stored section missing one key is read with that key's default; the other key is kept."""
    data = {'date_format': DATE_FORMAT, 'timezone': TIMEZONE}
    data.pop(missing_key)

    dao = build_date_settings(data)

    assert getattr(dao, missing_key) == DateSettingsDAO.__DEFAULT_SETTINGS__[missing_key]
    kept_key: str = 'timezone' if missing_key == 'date_format' else 'date_format'
    assert getattr(dao, kept_key) == data[kept_key]


@pytest.mark.parametrize('unusable', [None, '', 12, {'tz': 'UTC'}, ['UTC']],
                         ids=['null', 'empty', 'number', 'dict', 'list'])
def test_an_unusable_value_falls_back_to_its_default(unusable: object) -> None:
    """A value the write's schema would refuse - written before it, or by hand - reads as the default."""
    dao = build_date_settings({'date_format': unusable, 'timezone': unusable})

    assert dao.date_format == DateSettingsDAO.__DEFAULT_SETTINGS__['date_format']
    assert dao.timezone == DateSettingsDAO.__DEFAULT_SETTINGS__['timezone']


def test_an_empty_section_reads_as_the_defaults() -> None:
    """Nothing usable at all is the default settings, not an error."""
    dao = build_date_settings({'_id': 'date'})

    assert dao.to_json() == build_date_settings(DateSettingsDAO.__DEFAULT_SETTINGS__).to_json()
