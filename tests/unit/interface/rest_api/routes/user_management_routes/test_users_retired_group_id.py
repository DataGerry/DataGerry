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
Unit tests for the refusal of the retired single ``group_id`` on the user create and update request schemas

The validator drops an undeclared key, so the key is declared with a rule that always fails: a client still sending
it gets a 400 naming it instead of a user silently put into the default group. Run through Cerberus itself
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    RETIRED_GROUP_ID_KEY,
    RETIRED_GROUP_ID_MSG,
)
from cmdb.interface.rest_api.routes.user_management_routes.users_helper import with_retired_user_keys
from cmdb.interface.rest_api.routes.user_management_routes.users_routes import USER_CREATE_SCHEMA, USER_UPDATE_SCHEMA
# -------------------------------------------------------------------------------------------------------------------- #

GROUP: int = 5
CREATE_BODY: dict[str, Any] = {'user_name': 'retired-key', 'password': 'secret', 'active': True}
SCHEMAS: list[dict[str, Any]] = [USER_CREATE_SCHEMA, USER_UPDATE_SCHEMA]
SCHEMA_IDS: list[str] = ['create', 'update']


def _errors(schema: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """What the route's validator reports"""
    validator = Validator(schema, purge_unknown=True)
    validator.validate(body)

    return validator.errors


@pytest.mark.parametrize('schema', SCHEMAS, ids=SCHEMA_IDS)
@pytest.mark.parametrize('value', [GROUP, [GROUP], None, 'x'], ids=['int', 'list', 'null', 'string'])
def test_the_retired_key_is_refused_whatever_its_value(schema: dict[str, Any], value: Any) -> None:
    """Any value - also beside a valid group_ids"""
    errors = _errors(schema, {**CREATE_BODY, 'group_ids': [GROUP], RETIRED_GROUP_ID_KEY: value})

    assert RETIRED_GROUP_ID_KEY in errors


@pytest.mark.parametrize('schema', SCHEMAS, ids=SCHEMA_IDS)
def test_the_refusal_says_what_to_send_instead(schema: dict[str, Any]) -> None:
    """Names group_ids"""
    assert _errors(schema, {**CREATE_BODY, RETIRED_GROUP_ID_KEY: GROUP})[RETIRED_GROUP_ID_KEY] == [RETIRED_GROUP_ID_MSG]


@pytest.mark.parametrize('schema', SCHEMAS, ids=SCHEMA_IDS)
def test_a_body_without_it_passes(schema: dict[str, Any]) -> None:
    """The control"""
    assert _errors(schema, {**CREATE_BODY, 'group_ids': [GROUP]}) == {}


def test_the_given_schema_is_not_changed() -> None:
    """A copy carries the rule"""
    schema: dict[str, Any] = {'name': {'type': 'string'}}

    assert RETIRED_GROUP_ID_KEY in with_retired_user_keys(schema)
    assert RETIRED_GROUP_ID_KEY not in schema
