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
Unit tests for cmdb.class_schema.person_model.cmdb_person_schema - the ``/persons`` record body

Only the display name is required, as on the PERSON base fields; first and last name may be absent, empty or null
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.person_model.cmdb_person_schema import get_cmdb_person_schema
from cmdb.class_schema.write_schema_helper import build_write_schema
# -------------------------------------------------------------------------------------------------------------------- #

DISPLAY_NAME: str = 'ann.lee'


def _validator() -> Validator:
    """The validator the /persons write routes use"""
    return Validator(build_write_schema(get_cmdb_person_schema()), purge_unknown=True)


@pytest.mark.parametrize('names', [
    {}, {'first_name': '', 'last_name': ''}, {'first_name': None, 'last_name': None},
    {'first_name': 'Ann', 'last_name': 'Lee'},
], ids=['absent', 'empty', 'null', 'given'])
def test_first_and_last_name_are_optional(names: dict[str, Any]) -> None:
    """A display name is enough"""
    validator = _validator()

    assert validator.validate({'display_name': DISPLAY_NAME, **names}), validator.errors


@pytest.mark.parametrize('body', [{}, {'display_name': ''}], ids=['absent', 'empty'])
def test_the_display_name_is_required(body: dict[str, Any]) -> None:
    """The one name a person must have"""
    validator = _validator()

    assert not validator.validate(body)
    assert 'display_name' in validator.errors
