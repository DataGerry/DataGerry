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
Unit tests for cmdb.database.updater.versions.updater_20260417

The migration gives every CmdbType and CmdbObject a ``special_type`` key, writing the empty marker for
the ones that carry no SpecialType flavour. It was the lowest-covered file in the repository (58%) and
the only updater besides one already at 100% without a test module of its own: its registration was
covered, and every statement that does something was not.

What the queries have to say is the whole migration, so that is what is pinned here:

  - the filter selects **only** documents that lack the key, which is what makes a second run a no-op
    and a partial failure safe to repeat
  - the update writes the empty marker and touches nothing else - it must never assign a flavour, which
    only happens when a special type is created
  - the version is bumped **after** both collections, so an interrupted run repeats instead of being
    recorded as done

The end-to-end behaviour against a real MongoDB - including the double run - is
tests/integration/database/test_integration_updater_20260417.py, and the metadata contract is the
shared parametrized test in test_version_updaters
"""
# pylint: disable=no-member  # the managers are MagicMocks, so update_many carries call_args
from cmdb.database.updater.versions.updater_20260417 import (
    LEGACY_EMPTY_SPECIAL_TYPE,
    Update20260417,
)
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from tests.unit.database.updater.test_updater_version_bump_contract import (
    build_stubbed_updater,
)
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20260417


class TestMetadata:
    """The two values the runner reads before deciding to run anything."""

    def test_creation_date_is_the_registered_version(self) -> None:
        """It must equal the version registered in DatabaseUpdater.__UPDATE_VERSIONS__."""
        assert build_stubbed_updater(Update20260417).creation_date() == CREATION_DATE

    def test_the_description_says_what_actually_runs(self) -> None:
        """
        It is user-facing - the runner prints it per migration

        It used to claim the key was added 'to identify special CmdbTypes', which this migration does
        not do: it writes the EMPTY marker, and identification happens when a special type is created.
        """
        description = build_stubbed_updater(Update20260417).description()

        assert 'special_type' in description
        assert 'empty' in description.lower()


class TestTheQueriesAreTheMigration:
    """Both collections are updated with the same narrow filter and the same value."""

    def test_only_documents_lacking_the_key_are_selected(self) -> None:
        """
        The ``$exists: False`` filter is the whole of the re-run safety

        Anything broader would rewrite a type that already carries a real SpecialType flavour.
        """
        updater = build_stubbed_updater(Update20260417)

        updater.start_update()

        type_call = updater.types_manager.update_many.call_args.kwargs
        object_call = updater.objects_manager.update_many.call_args.kwargs

        assert type_call['criteria'] == {TypeSchemaKey.SPECIAL_TYPE.value: {'$exists': False}}
        assert object_call['criteria'] == {CmdbObjectKey.SPECIAL_TYPE.value: {'$exists': False}}

    def test_the_empty_marker_is_what_is_written(self) -> None:
        """
        Historically accurate on purpose

        The model settled on None afterwards; updater_20260908 converges the two. This migration keeps
        writing '' because a shipped migration must record what it did - databases past this version
        are never revisited.
        """
        updater = build_stubbed_updater(Update20260417)

        updater.start_update()

        assert updater.types_manager.update_many.call_args.kwargs['update'] == {
            TypeSchemaKey.SPECIAL_TYPE.value: LEGACY_EMPTY_SPECIAL_TYPE
        }
        assert updater.objects_manager.update_many.call_args.kwargs['update'] == {
            CmdbObjectKey.SPECIAL_TYPE.value: LEGACY_EMPTY_SPECIAL_TYPE
        }
        assert LEGACY_EMPTY_SPECIAL_TYPE == ''
