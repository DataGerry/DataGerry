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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper

Pure tests: no Mongo. The render path patches RenderList at the helper module path; the
validation helper drives a MagicMock ObjectsManager. Only the helpers' own branch logic is
exercised (view dispatch, the type-schema / field-name guards, the special_type comparison)
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    render_or_native,
    is_special_type_changed,
    validate_and_fill_object_fields,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectViewMode
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 render_or_native                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRenderOrNative:
    """render_or_native dispatches on the view mode and rejects unknown views with 400."""

    def test_native_returns_object_dicts(self) -> None:
        """The native view returns each object's __dict__ unchanged."""
        objects = [SimpleNamespace(public_id=1), SimpleNamespace(public_id=2)]

        result = render_or_native(ObjectViewMode.NATIVE, objects, MagicMock())

        assert result == [{'public_id': 1}, {'public_id': 2}]

    def test_render_delegates_to_render_list(self) -> None:
        """The render view delegates to RenderList(...).render_result_list(raw=True)."""
        objects = [SimpleNamespace()]

        with patch(f'{HELPER_PATH}.RenderList') as render_list_ctor:
            render_list_ctor.return_value.render_result_list.return_value = ['rendered']

            result = render_or_native(ObjectViewMode.RENDER, objects, MagicMock())

        assert result == ['rendered']
        render_list_ctor.return_value.render_result_list.assert_called_once_with(raw=True)

    def test_unknown_view_aborts_400(self) -> None:
        """An unrecognised view mode aborts with HTTP 400."""
        with pytest.raises(HTTPException) as exc_info:
            render_or_native('something-else', [], MagicMock())

        assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                              is_special_type_changed                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIsSpecialTypeChanged:
    """is_special_type_changed reports a difference between two special_type values."""

    @pytest.mark.parametrize('old,new,expected', [
        (None, None, False),
        ('SUBNET', 'SUBNET', False),
        (None, 'SUBNET', True),
        ('SUBNET', None, True),
        ('SUBNET', 'VLAN', True),
    ])
    def test_difference_detection(self, old: Any, new: Any, expected: bool) -> None:
        """Returns True only when the two values differ."""
        assert is_special_type_changed(old, new) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                          validate_and_fill_object_fields                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateAndFillObjectFields:
    """validate_and_fill_object_fields guards type / field validity and backfills the field type."""

    @staticmethod
    def _manager(type_schema: dict[str, Any] | None) -> MagicMock:
        """A MagicMock ObjectsManager whose get_object_type returns the given schema."""
        manager = MagicMock()
        manager.get_object_type.return_value = type_schema
        return manager

    def test_missing_type_id_aborts_400(self) -> None:
        """An object payload without type_id is rejected with 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(self._manager({'fields': []}), {'fields': []})

        assert exc_info.value.code == 400

    def test_missing_type_schema_aborts_400(self) -> None:
        """When the type cannot be resolved the request is rejected with 400 (not a 500 crash)."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(self._manager(None), {'type_id': 5, 'fields': []})

        assert exc_info.value.code == 400

    def test_unknown_field_aborts_400(self) -> None:
        """A field not declared by the type is rejected with 400."""
        manager = self._manager({'fields': [{'name': 'known', 'type': 'text'}]})

        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(manager, {'type_id': 5, 'fields': [{'name': 'ghost', 'value': 'x'}]})

        assert exc_info.value.code == 400

    def test_backfills_missing_field_type(self) -> None:
        """A field present in the type but missing its 'type' key gets the type backfilled in place."""
        manager = self._manager({'fields': [{'name': 'known', 'type': 'text'}]})
        object_data = {'type_id': 5, 'fields': [{'name': 'known', 'value': 'x'}]}

        validate_and_fill_object_fields(manager, object_data)

        assert object_data['fields'][0]['type'] == 'text'

    def test_validates_multi_data_section_rows(self) -> None:
        """MDS row fields are validated too: an unknown MDS field aborts with 400."""
        manager = self._manager({'fields': [{'name': 'known', 'type': 'text'}]})
        object_data = {
            'type_id': 5,
            'fields': [{'name': 'known', 'type': 'text', 'value': 'x'}],
            'multi_data_sections': [{'values': [{'data': [{'name': 'ghost', 'value': 'y'}]}]}],
        }

        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(manager, object_data)

        assert exc_info.value.code == 400
