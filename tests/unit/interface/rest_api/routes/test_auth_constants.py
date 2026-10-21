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
Unit tests for cmdb.interface.rest_api.routes.auth_constants.LOGIN_REQUEST_SCHEMA

The schema is the login's whole input check, run the way ``APIBlueprint.validate`` runs it (``purge_unknown``): the
frontend's two bodies pass unchanged, and each malformed one is refused naming its field
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.interface.rest_api.routes.auth_constants import LOGIN_REQUEST_SCHEMA, LoginKey
# -------------------------------------------------------------------------------------------------------------------- #

CREDENTIALS: dict[str, str] = {LoginKey.USER_NAME.value: 'admin', LoginKey.PASSWORD.value: 'admin'}

# What the frontend sends back as its chosen subscription in cloud mode's second step
CHOSEN_SUBSCRIPTION: dict[str, Any] = {'id': 's1', 'name': 'Sub 1', 'short_id': 'S1'}


def _validator() -> Validator:
    """The validator as the route's decorator builds it."""
    return Validator(LOGIN_REQUEST_SCHEMA, purge_unknown=True)


@pytest.mark.parametrize('body', [
    CREDENTIALS,
    {**CREDENTIALS, LoginKey.SUBSCRIPTION.value: CHOSEN_SUBSCRIPTION},
], ids=['first step', 'second step with the chosen subscription'])
def test_the_frontends_bodies_pass_unchanged(body: dict[str, Any]) -> None:
    """Both steps are accepted, and the subscription keeps every key the frontend sent"""
    validator = _validator()

    assert validator.validate(body)
    assert validator.document == body


def test_an_unknown_top_level_key_is_dropped() -> None:
    """Nothing but the contract reaches the route"""
    validator = _validator()

    assert validator.validate({**CREDENTIALS, 'remember_me': True})
    assert validator.document == CREDENTIALS


@pytest.mark.parametrize(('body', 'field'), [
    ({LoginKey.USER_NAME.value: 'admin'}, LoginKey.PASSWORD.value),
    ({LoginKey.PASSWORD.value: 'admin'}, LoginKey.USER_NAME.value),
    ({**CREDENTIALS, LoginKey.USER_NAME.value: {'$ne': 'nobody'}}, LoginKey.USER_NAME.value),
    ({**CREDENTIALS, LoginKey.USER_NAME.value: ['admin']}, LoginKey.USER_NAME.value),
    ({**CREDENTIALS, LoginKey.USER_NAME.value: ''}, LoginKey.USER_NAME.value),
    ({**CREDENTIALS, LoginKey.PASSWORD.value: 5}, LoginKey.PASSWORD.value),
    ({**CREDENTIALS, LoginKey.PASSWORD.value: ''}, LoginKey.PASSWORD.value),
    ({**CREDENTIALS, LoginKey.SUBSCRIPTION.value: 's1'}, LoginKey.SUBSCRIPTION.value),
    ({**CREDENTIALS, LoginKey.SUBSCRIPTION.value: {'name': 'Sub 1'}}, LoginKey.SUBSCRIPTION.value),
    ({**CREDENTIALS, LoginKey.SUBSCRIPTION.value: {'id': None}}, LoginKey.SUBSCRIPTION.value),
], ids=['no password', 'no user_name', 'query object', 'list', 'empty user_name', 'numeric password',
        'empty password', 'subscription string', 'subscription without id', 'subscription id null'])
def test_a_malformed_body_is_refused_naming_its_field(body: dict[str, Any], field: str) -> None:
    """Exactly the offending field is reported"""
    validator = _validator()

    assert not validator.validate(body)
    assert set(validator.errors) == {field}


def test_a_null_subscription_is_the_first_step() -> None:
    """The frontend may send the field empty before a choice is made"""
    assert _validator().validate({**CREDENTIALS, LoginKey.SUBSCRIPTION.value: None})
