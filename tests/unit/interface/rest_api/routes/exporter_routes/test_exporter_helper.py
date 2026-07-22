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
Unit tests for cmdb.interface.rest_api.routes.exporter_routes.exporter_helper
"""
import json
from http import HTTPStatus
from unittest.mock import patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.exporter_routes.exporter_helper import (
    resolve_export_format,
    build_types_json_export_response,
    SUPPORTED_EXPORT_FORMATS,
)
from cmdb.interface.rest_api.routes.exporter_routes.exporter_constants import (
    ZIP_EXPORT_FORMAT,
    DEFAULT_EXPORT_FORMAT,
    TYPE_EXPORT_MIMETYPE,
    TYPE_EXPORT_FILE_EXTENSION,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.routes.exporter_routes.exporter_helper'


class TestResolveExportFormat:
    """resolve_export_format picks + validates the export format from the optional params."""

    def test_no_params_uses_default_format(self) -> None:
        """With neither zip nor classname, the default format is used."""
        assert resolve_export_format({}) == DEFAULT_EXPORT_FORMAT

    def test_classname_is_used_when_supported(self) -> None:
        """An explicit, supported classname is returned as-is."""
        assert resolve_export_format({'classname': 'CsvExportFormat'}) == 'CsvExportFormat'

    @pytest.mark.parametrize('zip_value', ['true', 'True'])
    def test_truthy_zip_forces_zip_format(self, zip_value: str) -> None:
        """A truthy zip flag with a supported inner classname forces the ZIP wrapper."""
        assert resolve_export_format({'zip': zip_value, 'classname': 'CsvExportFormat'}) == ZIP_EXPORT_FORMAT

    def test_zip_with_unsupported_inner_classname_aborts_400(self) -> None:
        """A zip export with an unknown inner classname aborts 400 (guards the ZIP's inner load_class)."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_export_format({'zip': 'true', 'classname': 'Bogus'})
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_zip_without_inner_classname_aborts_400(self) -> None:
        """A zip export must name the inner format to pack; a missing classname aborts 400."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_export_format({'zip': 'true'})
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_zip_in_zip_is_rejected(self) -> None:
        """The ZIP wrapper cannot pack itself (zip-in-zip); it aborts 400."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_export_format({'zip': 'true', 'classname': ZIP_EXPORT_FORMAT})
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('zip_value', ['false', 'False', '', 'nonsense'])
    def test_non_truthy_zip_falls_back_to_classname(self, zip_value: str) -> None:
        """A non-truthy / unrecognised zip flag does not force ZIP; the classname (or default) wins."""
        assert resolve_export_format({'zip': zip_value}) == DEFAULT_EXPORT_FORMAT

    def test_unsupported_classname_aborts_400(self) -> None:
        """An unknown classname aborts 400 (whitelist guard against arbitrary load_class)."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_export_format({'classname': 'Bogus'})
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_zip_and_all_default_extensions_are_whitelisted(self) -> None:
        """The whitelist includes the ZIP wrapper and the built-in formats."""
        assert ZIP_EXPORT_FORMAT in SUPPORTED_EXPORT_FORMATS
        assert DEFAULT_EXPORT_FORMAT in SUPPORTED_EXPORT_FORMATS
        assert 'CsvExportFormat' in SUPPORTED_EXPORT_FORMATS


class TestBuildTypesJsonExportResponse:
    """build_types_json_export_response serializes types into a downloadable JSON attachment."""

    def test_serializes_types_as_json_attachment(self) -> None:
        """Types are serialized to a JSON list and returned as a timestamped .json attachment."""
        with patch(f'{MODULE_PATH}.CmdbType') as cmdb_type:
            cmdb_type.to_json.side_effect = lambda type_: {'public_id': type_}
            response = build_types_json_export_response([1, 2])

        assert response.status_code == HTTPStatus.OK
        assert response.mimetype == TYPE_EXPORT_MIMETYPE
        disposition = response.headers['Content-Disposition']
        assert 'attachment; filename=' in disposition
        assert disposition.endswith(f'.{TYPE_EXPORT_FILE_EXTENSION}')
        assert [entry['public_id'] for entry in json.loads(response.get_data(as_text=True))] == [1, 2]

    def test_empty_types_serialize_to_empty_list(self) -> None:
        """An empty type list produces a valid empty JSON export (200, body '[]'), not an error."""
        response = build_types_json_export_response([])

        assert response.status_code == HTTPStatus.OK
        assert json.loads(response.get_data(as_text=True)) == []
