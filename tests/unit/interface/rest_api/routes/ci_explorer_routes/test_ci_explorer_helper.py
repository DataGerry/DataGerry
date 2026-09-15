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

Pure tests with stub callables: load_ci_explorer_entity aborts 404 for an unknown entity and
otherwise reports the entity plus the field's previous value; record_tooltip_edit_log writes an EDIT
log naming the change and swallows a logging failure, because the object write it documents has
already happened. flask.abort raises a werkzeug HTTPException, so the status codes are asserted
without a Flask app context. The request schemas are checked against a real Cerberus Validator
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from cerberus import Validator
from werkzeug.exceptions import HTTPException

from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_helper import (
    TOOLTIP_LOG_COMMENT,
    get_ci_explorer_label_schema,
    get_ci_explorer_tooltip_schema,
    load_ci_explorer_entity,
    record_tooltip_edit_log,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 7
TOOLTIP_KEY: str = CmdbObjectKey.CI_EXPLORER_TOOLTIP.value
LABEL_KEY: str = TypeSchemaKey.CI_EXPLORER_LABEL.value
TOOLTIP_VALUE: str = 'a helpful tooltip'
PREVIOUS_TOOLTIP: str = 'the old tooltip'
ENTITY_LABEL: str = 'Object'
USER_ID: int = 42
USER_NAME: str = 'tester'
OBJECT_VERSION: str = '1.0.1'


def _request_user() -> MagicMock:
    """Builds a CmdbUser stub answering the two accessors the log helper uses."""
    request_user = MagicMock(name='request_user')
    request_user.get_public_id.return_value = USER_ID
    request_user.get_display_name.return_value = USER_NAME

    return request_user


class TestLoadCiExplorerEntity:
    """load_ci_explorer_entity resolves the entity a field write targets."""

    def test_missing_entity_aborts_404(self) -> None:
        """An unknown public_id is a 404 naming the entity."""
        with pytest.raises(HTTPException) as exc_info:
            load_ci_explorer_entity(lambda _id: None, PUBLIC_ID, TOOLTIP_KEY, ENTITY_LABEL)

        assert exc_info.value.code == HTTPStatus.NOT_FOUND

    def test_returns_the_entity_and_the_previous_value(self) -> None:
        """The entity is returned together with what the field held before."""
        entity: dict[str, Any] = {'public_id': PUBLIC_ID, TOOLTIP_KEY: PREVIOUS_TOOLTIP}

        loaded, previous = load_ci_explorer_entity(lambda _id: entity, PUBLIC_ID, TOOLTIP_KEY, ENTITY_LABEL)

        assert loaded is entity
        assert previous == PREVIOUS_TOOLTIP

    def test_unset_field_reports_none_as_previous_value(self) -> None:
        """An entity that never carried the field reports None rather than raising."""
        _loaded, previous = load_ci_explorer_entity(
            lambda _id: {'public_id': PUBLIC_ID}, PUBLIC_ID, TOOLTIP_KEY, ENTITY_LABEL,
        )

        assert previous is None


class TestRecordTooltipEditLog:
    """record_tooltip_edit_log puts a tooltip change into the object's history."""

    def test_writes_an_edit_log_naming_the_change(self) -> None:
        """The log records the object, the user, the comment and the old / new tooltip."""
        logs_manager = MagicMock(name='logs_manager')
        stored_object = {'public_id': PUBLIC_ID, 'version': OBJECT_VERSION}

        record_tooltip_edit_log(logs_manager, _request_user(), stored_object, PREVIOUS_TOOLTIP, TOOLTIP_VALUE)

        kwargs = logs_manager.insert_log.call_args.kwargs
        assert kwargs['action'] == LogAction.EDIT
        assert kwargs['object_id'] == PUBLIC_ID
        assert kwargs['version'] == OBJECT_VERSION
        assert kwargs['user_id'] == USER_ID
        assert kwargs['user_name'] == USER_NAME
        assert kwargs['comment'] == TOOLTIP_LOG_COMMENT
        assert kwargs['changes'] == [{
            'type': 'change',
            'name': TOOLTIP_KEY,
            'old': PREVIOUS_TOOLTIP,
            'new': TOOLTIP_VALUE,
        }]

    def test_logging_failure_is_swallowed(self) -> None:
        """The object was already written, so a failing log must not raise."""
        logs_manager = MagicMock(name='logs_manager')
        logs_manager.insert_log.side_effect = RuntimeError('boom')

        record_tooltip_edit_log(logs_manager, _request_user(), {'public_id': PUBLIC_ID}, None, TOOLTIP_VALUE)


class TestRequestSchemas:
    """The two field routes validate their one-key bodies."""

    @pytest.mark.parametrize('schema, key', [
        (get_ci_explorer_tooltip_schema(), TOOLTIP_KEY),
        (get_ci_explorer_label_schema(), LABEL_KEY),
    ], ids=['tooltip', 'label'])
    def test_accepts_a_string_and_purges_unknown_keys(self, schema: dict[str, Any], key: str) -> None:
        """A valid body passes and anything else in it is dropped rather than written."""
        validator = Validator(schema, purge_unknown=True)

        assert validator.validate({key: TOOLTIP_VALUE, 'active': False})
        assert validator.document == {key: TOOLTIP_VALUE}

    @pytest.mark.parametrize('schema, key', [
        (get_ci_explorer_tooltip_schema(), TOOLTIP_KEY),
        (get_ci_explorer_label_schema(), LABEL_KEY),
    ], ids=['tooltip', 'label'])
    def test_empty_string_clears_the_field(self, schema: dict[str, Any], key: str) -> None:
        """An empty value is how the field is cleared, so it must validate."""
        assert Validator(schema, purge_unknown=True).validate({key: ''})

    @pytest.mark.parametrize('schema', [get_ci_explorer_tooltip_schema(), get_ci_explorer_label_schema()],
                             ids=['tooltip', 'label'])
    def test_missing_key_is_rejected(self, schema: dict[str, Any]) -> None:
        """A body without the field is refused instead of silently writing nothing."""
        assert not Validator(schema, purge_unknown=True).validate({'unrelated': 'x'})

    @pytest.mark.parametrize('schema, key', [
        (get_ci_explorer_tooltip_schema(), TOOLTIP_KEY),
        (get_ci_explorer_label_schema(), LABEL_KEY),
    ], ids=['tooltip', 'label'])
    def test_non_string_value_is_rejected(self, schema: dict[str, Any], key: str) -> None:
        """The field holds text; a number or an object is refused."""
        assert not Validator(schema, purge_unknown=True).validate({key: 5})
