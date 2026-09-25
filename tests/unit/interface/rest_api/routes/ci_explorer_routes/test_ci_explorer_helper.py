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
Unit tests for the CI Explorer route helpers

Pure tests with stub callables: load_ci_explorer_entity aborts 404 for an unknown entity and otherwise
reports the entity plus the field's previous value. flask.abort raises a werkzeug HTTPException, so
the status codes are asserted without a Flask app context, and the request schema is checked against a
real Cerberus Validator.
"""
from http import HTTPStatus
from typing import Any
import pytest
from cerberus import Validator
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_helper import (
    get_ci_explorer_label_schema,
    load_ci_explorer_entity,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 7
LABEL_KEY: str = TypeSchemaKey.CI_EXPLORER_LABEL.value
LABEL_VALUE: str = 'hostname'
PREVIOUS_LABEL: str = 'serial'
ENTITY_LABEL: str = 'Type'


class TestLoadCiExplorerEntity:
    """
    load_ci_explorer_entity resolves the entity a field write targets

    Only the label field route uses it, but the entity and the field it reads are both parameters - it
    answers 404 for whatever it is pointed at.
    """

    def test_missing_entity_aborts_404(self) -> None:
        """An unknown public_id is a 404 naming the entity."""
        with pytest.raises(HTTPException) as exc_info:
            load_ci_explorer_entity(lambda _id: None, PUBLIC_ID, LABEL_KEY, ENTITY_LABEL)

        assert exc_info.value.code == HTTPStatus.NOT_FOUND

    def test_returns_the_entity_and_the_previous_value(self) -> None:
        """The entity is returned together with what the field held before."""
        entity: dict[str, Any] = {'public_id': PUBLIC_ID, LABEL_KEY: PREVIOUS_LABEL}

        loaded, previous = load_ci_explorer_entity(lambda _id: entity, PUBLIC_ID, LABEL_KEY, ENTITY_LABEL)

        assert loaded is entity
        assert previous == PREVIOUS_LABEL

    def test_unset_field_reports_none_as_previous_value(self) -> None:
        """An entity that never carried the field reports None rather than raising."""
        _loaded, previous = load_ci_explorer_entity(
            lambda _id: {'public_id': PUBLIC_ID}, PUBLIC_ID, LABEL_KEY, ENTITY_LABEL,
        )

        assert previous is None


class TestRequestSchema:
    """The label-field route validates its one-key body."""

    def test_accepts_a_string_and_purges_unknown_keys(self) -> None:
        """A valid body passes and anything else in it is dropped rather than written."""
        validator = Validator(get_ci_explorer_label_schema(), purge_unknown=True)

        assert validator.validate({LABEL_KEY: LABEL_VALUE, 'active': False})
        assert validator.document == {LABEL_KEY: LABEL_VALUE}

    def test_empty_string_clears_the_field(self) -> None:
        """An empty value is how the nomination is cleared, so it must validate."""
        assert Validator(get_ci_explorer_label_schema(), purge_unknown=True).validate({LABEL_KEY: ''})

    def test_missing_key_is_rejected(self) -> None:
        """A body without the field is refused instead of silently writing nothing."""
        assert not Validator(get_ci_explorer_label_schema(), purge_unknown=True).validate(
            {'unrelated': 'x'},
        )

    def test_non_string_value_is_rejected(self) -> None:
        """The field holds a field NAME; a number or an object is refused."""
        assert not Validator(get_ci_explorer_label_schema(), purge_unknown=True).validate({LABEL_KEY: 5})
