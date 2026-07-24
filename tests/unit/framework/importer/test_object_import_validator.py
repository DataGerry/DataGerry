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
Unit tests for cmdb.framework.importer.helper.object_import_validator

DB-free. Covers the strict import-bool parser and the per-object normalization+validation: forced
lifecycle fields, type-derived special_type, defaulted optional fields, and the active validation
(default when absent/empty, reject when an unrecognised value is provided).
"""
from datetime import datetime

import pytest

from cmdb.framework.importer.helper.object_import_validator import (
    parse_import_bool,
    normalize_and_validate_object,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #


class TestParseImportBool:
    """The strict import-bool parser."""

    @pytest.mark.parametrize('value', [True, 1, '1', 'true', 'True', 'TRUE', 'yes', 'Yes', ' yes '])
    def test_truthy(self, value) -> None:
        """Accepted truthy forms parse to True."""
        assert parse_import_bool(value) is True

    @pytest.mark.parametrize('value', [False, 0, '0', 'false', 'False', 'FALSE', 'no', 'No', ' NO '])
    def test_falsy(self, value) -> None:
        """Accepted falsy forms parse to False."""
        assert parse_import_bool(value) is False

    @pytest.mark.parametrize('value', ['maybe', 2, '2', -1, None, '', 'y', 'n', [], {}])
    def test_invalid_returns_none(self, value) -> None:
        """Any unrecognised value returns None (rejected)."""
        assert parse_import_bool(value) is None


class TestNormalizeAndValidateObject:
    """Per-object normalization + validation."""

    def test_forces_lifecycle_fields(self) -> None:
        """version/creation_time/last_edit_time/editor_id are forced, ignoring provided values."""
        obj = {'version': '9.9', 'last_edit_time': 'x', 'editor_id': 42, 'creation_time': 'old'}

        errors = normalize_and_validate_object(obj, None)

        assert not errors
        assert obj['version'] == '1.0.0'
        assert obj['last_edit_time'] is None
        assert obj['editor_id'] is None
        assert isinstance(obj['creation_time'], datetime)

    def test_special_type_is_taken_from_the_type(self) -> None:
        """special_type is set from the target type, ignoring any provided value."""
        obj = {'special_type': 'SUPERNET'}

        normalize_and_validate_object(obj, SpecialType.SUBNET)

        assert obj['special_type'] == SpecialType.SUBNET

    def test_special_type_none_when_type_has_none(self) -> None:
        """special_type defaults to None when the type has no special type."""
        obj: dict = {}

        normalize_and_validate_object(obj, None)

        assert obj['special_type'] is None

    def test_ci_explorer_tooltip_kept_or_defaulted(self) -> None:
        """A provided ci_explorer_tooltip is kept; an absent one defaults to None."""
        provided = {'ci_explorer_tooltip': 'hover me'}
        absent: dict = {}

        normalize_and_validate_object(provided, None)
        normalize_and_validate_object(absent, None)

        assert provided['ci_explorer_tooltip'] == 'hover me'
        assert absent['ci_explorer_tooltip'] is None

    def test_active_defaults_true_when_absent_or_empty(self) -> None:
        """active defaults to True when absent, None, or an empty string."""
        for obj in ({}, {'active': None}, {'active': ''}):
            assert not normalize_and_validate_object(obj, None)
            assert obj['active'] is True

    def test_active_valid_value_is_coerced(self) -> None:
        """A recognised active value is coerced to a real bool."""
        obj = {'active': 'no'}

        assert not normalize_and_validate_object(obj, None)
        assert obj['active'] is False

    def test_active_invalid_value_is_rejected(self) -> None:
        """An unrecognised active value produces an error (and the object is a reject)."""
        obj = {'active': 'maybe'}

        errors = normalize_and_validate_object(obj, None)

        assert errors == ["Invalid value for 'active': 'maybe'"]
