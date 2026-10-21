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
Unit tests for cmdb.class_schema.settings_model.date_settings_schema

Pure Cerberus tests with the validator the route's ``@validate`` builds (``purge_unknown=True``): both values are
required, non-empty strings within their caps; their content is not interpreted
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.settings.date_settings import DateSettingsDAO
from cmdb.settings.date_settings_constants import DATE_FORMAT_MAX_LENGTH, TIMEZONE_MAX_LENGTH
# -------------------------------------------------------------------------------------------------------------------- #

DATE_FORMAT: str = 'YYYY-MM-DDTHH:mm'
TIMEZONE: str = 'Europe/Berlin'


def _validator() -> Validator:
    """The validator ``APIBlueprint.validate`` builds for the write"""
    return Validator(DateSettingsDAO.SCHEMA, purge_unknown=True)


def _body(**overrides: Any) -> dict[str, Any]:
    """A valid body with the given keys replaced"""
    return {'date_format': DATE_FORMAT, 'timezone': TIMEZONE, **overrides}


def test_the_frontend_body_is_accepted() -> None:
    """Exactly what the settings form posts"""
    assert _validator().validate(_body())


@pytest.mark.parametrize('date_format', ['YYYY-MM-DD', 'YYYY-MM-DDTHH:mm:ssZ', 'DD.MM.YYYY HH:mm'])
def test_any_format_string_is_accepted(date_format: str) -> None:
    """The format is moment.js syntax, which only the frontend reads; it is not parsed here"""
    assert _validator().validate(_body(date_format=date_format))


@pytest.mark.parametrize('timezone', ['UTC', 'Europe/Berlin', 'America/Argentina/ComodRivadavia', 'Etc/GMT+5'])
def test_any_timezone_name_is_accepted(timezone: str) -> None:
    """moment-timezone names, including a 32-character one and a link name, are not checked against zoneinfo"""
    assert _validator().validate(_body(timezone=timezone))


@pytest.mark.parametrize('key', ['date_format', 'timezone'])
def test_a_missing_key_is_refused_and_named(key: str) -> None:
    """The route used to answer this with a 500"""
    body: dict[str, Any] = _body()
    body.pop(key)
    validator: Validator = _validator()

    assert not validator.validate(body)
    assert key in validator.errors


@pytest.mark.parametrize('key', ['date_format', 'timezone'])
@pytest.mark.parametrize('value', [None, '', 12, True, {'tz': 'UTC'}, ['UTC']],
                         ids=['null', 'empty', 'number', 'boolean', 'dict', 'list'])
def test_a_value_that_is_no_non_empty_string_is_refused(key: str, value: Any) -> None:
    """It would reach the date pipe of every page"""
    validator: Validator = _validator()

    assert not validator.validate(_body(**{key: value}))
    assert key in validator.errors


@pytest.mark.parametrize(('key', 'cap'), [('date_format', DATE_FORMAT_MAX_LENGTH), ('timezone', TIMEZONE_MAX_LENGTH)])
def test_the_length_caps(key: str, cap: int) -> None:
    """The cap itself is accepted, one character more is refused"""
    assert _validator().validate(_body(**{key: 'x' * cap}))
    assert not _validator().validate(_body(**{key: 'x' * (cap + 1)}))


def test_an_echoed_id_and_extra_keys_are_dropped() -> None:
    """The validator purges what the schema does not declare, so the handler never sees it"""
    validator: Validator = _validator()

    assert validator.validate(_body(_id='date', unexpected='value'))
    assert validator.document == _body()
