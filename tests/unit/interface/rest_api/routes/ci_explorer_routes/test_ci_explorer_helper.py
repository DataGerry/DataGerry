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
Unit tests for the CI Explorer route helper ``apply_ci_explorer_field``

Pure tests with stub fetch/persist callables: a missing entity aborts 404, a missing body field
aborts 400, and a valid call sets the field on the fetched entity, persists it, and returns the
value. flask.abort raises a werkzeug HTTPException, so the status codes are asserted without a Flask
app context
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import CiExplorerField
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_helper import apply_ci_explorer_field
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 7
TOOLTIP_VALUE: str = 'a helpful tooltip'
ENTITY_LABEL: str = 'Object'


def test_missing_entity_aborts_404() -> None:
    """When the entity does not exist the helper aborts 404 and never persists."""
    persist = MagicMock(name='persist')

    with pytest.raises(HTTPException) as exc_info:
        apply_ci_explorer_field(
            lambda _id: None, persist, PUBLIC_ID, CiExplorerField.TOOLTIP,
            {CiExplorerField.TOOLTIP.value: TOOLTIP_VALUE}, ENTITY_LABEL,
        )

    assert exc_info.value.code == HTTPStatus.NOT_FOUND
    persist.assert_not_called()


@pytest.mark.parametrize('body', [None, {}, {'unrelated': 'x'}])
def test_missing_field_in_body_aborts_400(body: dict[str, Any] | None) -> None:
    """When the field is absent from the body the helper aborts 400 and never persists."""
    persist = MagicMock(name='persist')

    with pytest.raises(HTTPException) as exc_info:
        apply_ci_explorer_field(
            lambda _id: {'public_id': PUBLIC_ID}, persist, PUBLIC_ID, CiExplorerField.TOOLTIP,
            body, ENTITY_LABEL,
        )

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    persist.assert_not_called()


def test_valid_call_sets_field_persists_and_returns_value() -> None:
    """A valid call writes the field onto the entity, persists it, and returns the value."""
    entity: dict[str, Any] = {'public_id': PUBLIC_ID}
    persist = MagicMock(name='persist')

    result = apply_ci_explorer_field(
        lambda _id: entity, persist, PUBLIC_ID, CiExplorerField.TOOLTIP,
        {CiExplorerField.TOOLTIP.value: TOOLTIP_VALUE}, ENTITY_LABEL,
    )

    assert result == TOOLTIP_VALUE
    assert entity[CiExplorerField.TOOLTIP.value] == TOOLTIP_VALUE
    persist.assert_called_once_with(PUBLIC_ID, entity)
