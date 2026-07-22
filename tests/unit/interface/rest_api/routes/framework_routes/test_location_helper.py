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
Unit tests for the CmdbLocation route helpers

``resolve_location_name`` is exercised with ObjectsManager / RenderList / CmdbObject patched at
the helper module path - no Mongo and no rendering pipeline runs, only the name-derivation
branching. ``build_location_forest`` is exercised against the real ``LocationNode`` (pure logic)
to pin the flat-list -> nested-forest assembly the ``/locations/tree`` route delegates to.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    resolve_location_name,
    build_location_forest,
    parse_required_int,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper'

OBJECT_ID: int = 4242
ROOT_PUBLIC_ID: int = 1

EXPLICIT_NAME: str = 'Server Room A'
RENDERED_SUMMARY: str = 'Rendered Summary Line'
FALLBACK_NAME: str = f'ObjectID: {OBJECT_ID}'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404

PARENT_ID: int = 10
CHILD_ID: int = 11
GRANDCHILD_ID: int = 12
SECOND_ROOT_ID: int = 20


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app so ``abort`` resolves inside a request context."""
    return Flask(__name__)


def _location(public_id: int, parent: int) -> dict[str, Any]:
    """Builds a minimal CmdbLocation dict accepted by ``LocationNode`` / ``build_location_forest``."""
    return {
        'public_id': public_id,
        'name': f'loc-{public_id}',
        'parent': parent,
        'type_icon': 'fas fa-cube',
        'object_id': public_id + 100,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  parse_required_int                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestParseRequiredInt:
    """``parse_required_int`` coerces a required body field to int or aborts 400."""

    def test_returns_int_for_valid_value(self, flask_app: Flask) -> None:
        """A present, numeric value is coerced to int."""
        with flask_app.test_request_context():
            assert parse_required_int({'object_id': '42'}, 'object_id') == 42

    def test_missing_key_aborts_400(self, flask_app: Flask) -> None:
        """A missing key aborts 400 instead of raising a KeyError."""
        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as excinfo:
                parse_required_int({}, 'object_id')

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_non_integer_value_aborts_400(self, flask_app: Flask) -> None:
        """A non-integer value aborts 400 instead of raising a ValueError."""
        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as excinfo:
                parse_required_int({'object_id': 'not-an-int'}, 'object_id')

        assert excinfo.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                resolve_location_name                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveLocationName:
    """``resolve_location_name`` returns an explicit name or derives one from the linked object."""

    def test_explicit_name_is_returned_without_touching_the_object(self, flask_app: Flask) -> None:
        """A non-empty name short-circuits: the ObjectsManager is never queried."""
        objects_manager = MagicMock(name='objects_manager')

        with flask_app.test_request_context():
            result = resolve_location_name(EXPLICIT_NAME, OBJECT_ID, objects_manager, MagicMock())

        assert result == EXPLICIT_NAME
        objects_manager.get_object.assert_not_called()

    def test_empty_name_derives_from_rendered_summary_line(self, flask_app: Flask) -> None:
        """An empty name is replaced by the linked object's rendered ``summary_line``."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = {'public_id': OBJECT_ID}

        with patch(f'{HELPER_PATH}.CmdbObject.from_data'), \
             patch(f'{HELPER_PATH}.RenderList') as render_list_ctor, \
             flask_app.test_request_context():
            render_list_ctor.return_value.render_result_list.return_value = [{'summary_line': RENDERED_SUMMARY}]
            result = resolve_location_name('', OBJECT_ID, objects_manager, MagicMock())

        assert result == RENDERED_SUMMARY

    def test_empty_summary_line_falls_back_to_object_id_template(self, flask_app: Flask) -> None:
        """When the summary line is also empty the ``ObjectID: <id>`` template is used."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = {'public_id': OBJECT_ID}

        with patch(f'{HELPER_PATH}.CmdbObject.from_data'), \
             patch(f'{HELPER_PATH}.RenderList') as render_list_ctor, \
             flask_app.test_request_context():
            render_list_ctor.return_value.render_result_list.return_value = [{'summary_line': ''}]
            result = resolve_location_name(None, OBJECT_ID, objects_manager, MagicMock())

        assert result == FALLBACK_NAME

    def test_missing_object_aborts_404(self, flask_app: Flask) -> None:
        """A name that must be derived from a non-existent object aborts 404."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = None

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as excinfo:
                resolve_location_name('', OBJECT_ID, objects_manager, MagicMock())

        assert excinfo.value.code == HTTP_NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_location_forest                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildLocationForest:
    """``build_location_forest`` assembles a flat dict list into nested root trees."""

    def test_empty_input_yields_empty_forest(self) -> None:
        """No locations produce no roots."""
        assert build_location_forest([]) == []

    def test_only_root_parented_locations_become_roots(self) -> None:
        """Exactly the locations whose ``parent`` is the root id become forest roots."""
        locations = [
            _location(PARENT_ID, ROOT_PUBLIC_ID),
            _location(SECOND_ROOT_ID, ROOT_PUBLIC_ID),
            _location(CHILD_ID, PARENT_ID),  # not a root - nested below PARENT_ID
        ]

        forest = build_location_forest(locations)

        assert sorted(root['public_id'] for root in forest) == [PARENT_ID, SECOND_ROOT_ID]

    def test_descendants_are_nested_under_their_root(self) -> None:
        """A child and grandchild are nested beneath their root rather than appearing at top level."""
        locations = [
            _location(PARENT_ID, ROOT_PUBLIC_ID),
            _location(CHILD_ID, PARENT_ID),
            _location(GRANDCHILD_ID, CHILD_ID),
        ]

        forest = build_location_forest(locations)

        assert [root['public_id'] for root in forest] == [PARENT_ID]
        assert [child['public_id'] for child in forest[0]['children']] == [CHILD_ID]
        assert [gc['public_id'] for gc in forest[0]['children'][0]['children']] == [GRANDCHILD_ID]

    def test_orphan_without_root_parent_is_dropped(self) -> None:
        """A location whose parent is neither the root nor present is not surfaced as a root."""
        locations = [_location(CHILD_ID, PARENT_ID)]  # PARENT_ID is absent and is not the root id

        assert build_location_forest(locations) == []
