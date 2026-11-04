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
Unit tests: the route helpers that end in a catch-all let a database outage through unchanged

``_run_object_import``, ``_resolve_import_type`` (object import), ``clean_type_reports``,
``handle_delete_object_location``, ``run_alignment_step`` and the type import (``run_type_import_batch`` and its
per-entry steps) each answer an unexpected error their own way - a 500, a 400, a step error, a failed entry. A lost
connection or a lock timeout is none of those: it passes through as raised, so the route's ``handle_route_errors``
leaves it to the app's handlers (503 / 423). Each helper's own answer for any other error is pinned beside it
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.errors.database import DatabaseConnectionError, DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.types_manager import TypesManagerAlignmentError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_alignment_helper import clean_type_reports
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    handle_delete_object_location,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import TypeAlignmentStep
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import run_alignment_step
from cmdb.interface.rest_api.routes.importer_routes import importer_object_routes
from cmdb.interface.rest_api.routes.importer_routes.importer_type_helper import (
    read_type_to_update,
    run_type_import_batch,
)
# -------------------------------------------------------------------------------------------------------------------- #

OUTAGES: list[Exception] = [
    DocumentNetworkError('lost'), DocumentLockTimeoutError('locked'), DatabaseConnectionError('no connection'),
]
OUTAGE_IDS: list[str] = ['network', 'lock', 'connection']
INTERNAL_SERVER_ERROR: int = 500
BAD_REQUEST: int = 400
TYPE_ENTRY_ID: int = 4711


def _raising(failure: Exception) -> MagicMock:
    """A callable that raises ``failure``"""
    return MagicMock(side_effect=failure)


@pytest.mark.parametrize('outage', OUTAGES, ids=OUTAGE_IDS)
class TestAnOutagePassesThrough:
    """Raised as it was - the very object, not a wrapper"""

    def test_running_the_object_import(self, outage: Exception) -> None:
        """_run_object_import"""
        importer = MagicMock(start_import=_raising(outage))

        with pytest.raises(type(outage)) as exc_info:
            importer_object_routes._run_object_import(importer)  # pylint: disable=protected-access

        assert exc_info.value is outage

    def test_resolving_the_import_type(self, outage: Exception) -> None:
        """_resolve_import_type - it used to answer 400"""
        types_manager = MagicMock(get_type=_raising(outage))

        with pytest.raises(type(outage)) as exc_info:
            importer_object_routes._resolve_import_type(  # pylint: disable=protected-access
                {'type_id': 1}, MagicMock(), types_manager,
            )

        assert exc_info.value is outage

    def test_cleaning_the_reports(self, outage: Exception) -> None:
        """clean_type_reports"""
        reports_manager = MagicMock(strip_removed_fields_from_reports=_raising(outage))

        with pytest.raises(type(outage)) as exc_info:
            clean_type_reports(reports_manager, [{}], {'gone'}, MagicMock())

        assert exc_info.value is outage

    def test_deleting_the_location(self, outage: Exception) -> None:
        """handle_delete_object_location"""
        locations_manager = MagicMock(get_location_for_object=_raising(outage))

        with pytest.raises(type(outage)) as exc_info:
            handle_delete_object_location(MagicMock(), 1, locations_manager, MagicMock())

        assert exc_info.value is outage

    def test_an_alignment_step(self, outage: Exception) -> None:
        """run_alignment_step - not wrapped into the step error"""
        with pytest.raises(type(outage)) as exc_info:
            run_alignment_step(TypeAlignmentStep.LOCATIONS, _raising(outage))

        assert exc_info.value is outage

    def test_the_type_import_batch(self, outage: Exception) -> None:
        """run_type_import_batch - the batch stops instead of failing every remaining entry"""
        import_entry = MagicMock(side_effect=[None, outage, None])

        with pytest.raises(type(outage)) as exc_info:
            run_type_import_batch([{}, {}, {}], import_entry)

        assert exc_info.value is outage
        assert import_entry.call_count == 2

    def test_a_type_import_entry_step(self, outage: Exception) -> None:
        """read_type_to_update - one of the per-entry steps"""
        types_manager = MagicMock(get_type_instance=_raising(outage))

        with pytest.raises(type(outage)) as exc_info:
            read_type_to_update({'public_id': TYPE_ENTRY_ID}, types_manager, MagicMock())

        assert exc_info.value is outage


class TestAnyOtherErrorKeepsTheHelpersAnswer:
    """What the catch-all is still for"""

    def test_running_the_object_import_is_a_500(self) -> None:
        """Unexpected import error"""
        with pytest.raises(HTTPException) as exc_info:
            importer_object_routes._run_object_import(  # pylint: disable=protected-access
                MagicMock(start_import=_raising(RuntimeError('a bug'))),
            )

        assert exc_info.value.code == INTERNAL_SERVER_ERROR

    def test_resolving_the_import_type_is_a_400(self) -> None:
        """Unchanged"""
        with pytest.raises(HTTPException) as exc_info:
            importer_object_routes._resolve_import_type(  # pylint: disable=protected-access
                {'type_id': 1}, MagicMock(), MagicMock(get_type=_raising(RuntimeError('a bug'))),
            )

        assert exc_info.value.code == BAD_REQUEST

    def test_cleaning_the_reports_is_a_500(self) -> None:
        """Unchanged"""
        reports_manager = MagicMock(strip_removed_fields_from_reports=_raising(RuntimeError('a bug')))

        with pytest.raises(HTTPException) as exc_info:
            clean_type_reports(reports_manager, [{}], {'gone'}, MagicMock())

        assert exc_info.value.code == INTERNAL_SERVER_ERROR

    def test_deleting_the_location_is_a_500(self) -> None:
        """Unchanged"""
        with pytest.raises(HTTPException) as exc_info:
            handle_delete_object_location(
                MagicMock(), 1, MagicMock(get_location_for_object=_raising(RuntimeError('a bug'))), MagicMock(),
            )

        assert exc_info.value.code == INTERNAL_SERVER_ERROR

    def test_an_alignment_step_names_itself(self) -> None:
        """Wrapped with the step's name"""
        failure = RuntimeError('a bug')

        with pytest.raises(TypesManagerAlignmentError) as exc_info:
            run_alignment_step(TypeAlignmentStep.LOCATIONS, _raising(failure))

        assert exc_info.value.step == TypeAlignmentStep.LOCATIONS.value
        assert exc_info.value.__cause__ is failure

    def test_the_type_import_batch_fails_the_entry_only(self) -> None:
        """The others still import"""
        import_entry = MagicMock(side_effect=[None, RuntimeError('a bug'), None])

        report: Any = run_type_import_batch([{}, {}, {}], import_entry)

        assert import_entry.call_count == 3
        assert report.success_imports == 2

    def test_a_type_import_entry_step_reports_the_entry(self) -> None:
        """A message, no exception"""
        old_type, message = read_type_to_update(
            {'public_id': TYPE_ENTRY_ID}, MagicMock(get_type_instance=_raising(RuntimeError('a bug'))), MagicMock(),
        )

        assert old_type is None and message
