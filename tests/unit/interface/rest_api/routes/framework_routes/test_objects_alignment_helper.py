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
Unit tests for the re-alignment of stored objects after their type changed (cmdb_objects.objects_alignment_helper)
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.manager.objects_propagation_helper import (
    build_add_field_update,
    build_remove_undeclared_fields_update,
)
from cmdb.errors.manager.objects_manager import ObjectsManagerUpdateError
from cmdb.errors.manager.reports_manager import ReportsManagerUpdateError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_alignment_helper import (
    clean_type_reports,
    realign_objects_to_type,
)
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_INTERNAL_SERVER_ERROR: int = 500


# -------------------------------------------------------------------------------------------------------------------- #
#                                               realign_objects_to_type                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRealignObjectsToType:
    """
    realign_objects_to_type hands the objects manager server-side statements - it reads no object

    One pull of every name the type does not declare, then one push per declared field that only
    matches the objects lacking it, seeded with the field's default.
    """

    @staticmethod
    def _type(fields: list[dict[str, Any]], public_id: int = 1) -> SimpleNamespace:
        """A CmdbType stand-in exposing only .fields and .public_id."""
        return SimpleNamespace(fields=fields, public_id=public_id)

    def test_pulls_the_undeclared_names_and_pushes_every_declared_field(self) -> None:
        """The statements cover both halves of the drift, whatever the objects hold"""
        objects_manager = MagicMock()
        type_instance = self._type([
            {'name': 'keep', 'type': 'text'},
            {'name': 'added', 'type': 'date', 'value': 'def'},
        ], public_id=5)

        realign_objects_to_type(objects_manager, type_instance)

        objects_manager.apply_raw_updates.assert_called_once_with([
            build_remove_undeclared_fields_update(5, ['added', 'keep']),
            build_add_field_update(5, {'name': 'keep', 'type': 'text', 'value': None}),
            build_add_field_update(5, {'name': 'added', 'type': 'date', 'value': 'def'}),
        ])

    def test_reads_no_object(self) -> None:
        """Nothing is loaded to decide the drift - the statements match what needs changing"""
        objects_manager = MagicMock()

        realign_objects_to_type(objects_manager, self._type([{'name': 'keep', 'type': 'text'}]))

        objects_manager.get_objects_by.assert_not_called()

    def test_a_type_without_fields_only_pulls(self) -> None:
        """With nothing declared every flat entry is stale"""
        objects_manager = MagicMock()

        realign_objects_to_type(objects_manager, self._type([], public_id=6))

        objects_manager.apply_raw_updates.assert_called_once_with([build_remove_undeclared_fields_update(6, [])])

    def test_a_failing_statement_aborts_500(self) -> None:
        """A write failure surfaces as a 500, the route's answer for a broken re-alignment"""
        objects_manager = MagicMock()
        objects_manager.apply_raw_updates.side_effect = ObjectsManagerUpdateError('boom')

        with pytest.raises(HTTPException) as exc_info:
            realign_objects_to_type(objects_manager, self._type([{'name': 'keep', 'type': 'text'}]))

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                               clean_type_reports                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCleanTypeReports:
    """clean_type_reports is the route-layer wrapper: it delegates and maps failures to 500.

    The stripping itself lives on ReportsManager, so the section-template removal and the database
    updaters can reuse it; its own tests pin what it strips.
    """

    def test_delegates_to_the_reports_manager(self) -> None:
        """The arguments are handed straight to the manager operation."""
        reports_manager = MagicMock()
        reports = [{'public_id': 1}]
        type_instance = MagicMock()

        clean_type_reports(reports_manager, reports, {'gone'}, type_instance)

        reports_manager.strip_removed_fields_from_reports.assert_called_once_with(
            reports, {'gone'}, type_instance,
        )

    def test_noop_when_nothing_removed(self) -> None:
        """No removed field names means no report write (the manager short-circuits)."""
        reports_manager = MagicMock()

        clean_type_reports(reports_manager, [{'public_id': 1}], set(), MagicMock())

        reports_manager.bulk_write.assert_not_called()

    def test_manager_failure_maps_to_500(self) -> None:
        """A failed report write surfaces as an internal server error, not as a manager exception."""
        reports_manager = MagicMock()
        reports_manager.strip_removed_fields_from_reports.side_effect = ReportsManagerUpdateError('boom')

        with pytest.raises(HTTPException) as exc_info:
            clean_type_reports(reports_manager, [{'public_id': 1}], {'gone'}, MagicMock())

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR
