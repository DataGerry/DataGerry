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
Unit tests for cmdb.database.updater.versions.updater_20260908

The migration converges the two no-flavour spellings of ``special_type`` - the ``''`` written by
``updater_20260417`` and a key that was never written at all - onto the ``None`` the model and both
Cerberus schemas use.

The filter is the whole migration, and the thing worth pinning is how **narrow** it is: it matches
those two states and nothing else. A document already carrying null must not match (or a re-run
rewrites the collection), and one carrying a real SpecialType member must not match under any
circumstances - this migration must not be able to un-assign a RACK or a SUBNET.

The end-to-end behaviour, the double run and the two-migration sequence are in
tests/integration/database/test_integration_updater_20260417.py, which covers both updaters together;
the metadata contract is the shared parametrized test in test_version_updaters
"""
# pylint: disable=protected-access,no-member  # the criteria builder is internal and is the
# migration itself; the managers are MagicMocks, so update_many carries call_args
import pytest

from cmdb.database.updater.versions.updater_20260417 import LEGACY_EMPTY_SPECIAL_TYPE
from cmdb.database.updater.versions.updater_20260908 import NO_SPECIAL_TYPE, Update20260908
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from tests.unit.database.updater.test_updater_version_bump_contract import (
    build_stubbed_updater,
)
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20260908
SPECIAL_TYPE_KEY: str = TypeSchemaKey.SPECIAL_TYPE.value


def _matches(criteria: dict, stored_document: dict) -> bool:
    """
    Evaluates the migration's ``$or`` filter against one document, the way MongoDB would

    Only the two operators the filter uses are interpreted - an equality match and ``$exists`` - which
    is all this criteria contains. It lets the *selection rule* be asserted per document state without
    a database; the integration suite proves the same against a real collection.

    Args:
        criteria (dict): The migration's filter for one collection
        stored_document (dict): A stored document to test

    Returns:
        bool: True if MongoDB would select the document
    """
    for clause in criteria['$or']:
        (key, condition), = clause.items()

        if isinstance(condition, dict) and '$exists' in condition:
            if (key in stored_document) == condition['$exists']:
                return True
        elif key in stored_document and stored_document[key] == condition:
            return True

    return False


class TestTheFilterIsNarrow:
    """It selects the two legacy spellings, and nothing else."""

    def test_the_empty_marker_is_selected(self) -> None:
        """The state updater_20260417 left behind."""
        criteria = Update20260908._legacy_marker_criteria(SPECIAL_TYPE_KEY)

        assert _matches(criteria, {SPECIAL_TYPE_KEY: LEGACY_EMPTY_SPECIAL_TYPE}) is True

    def test_a_missing_key_is_selected(self) -> None:
        """A database that never ran the backfill converges too."""
        criteria = Update20260908._legacy_marker_criteria(SPECIAL_TYPE_KEY)

        assert _matches(criteria, {'public_id': 1}) is True

    def test_a_document_already_normalised_is_not_selected(self) -> None:
        """
        Which is what makes a second run a no-op

        A null marker is the target state, so matching it would rewrite the whole collection on every
        repeat and report a modified_count that suggests work was needed.
        """
        criteria = Update20260908._legacy_marker_criteria(SPECIAL_TYPE_KEY)

        assert _matches(criteria, {SPECIAL_TYPE_KEY: NO_SPECIAL_TYPE}) is False

    @pytest.mark.parametrize('flavour', [special_type.value for special_type in SpecialType])
    def test_a_real_flavour_is_never_selected(self, flavour: str) -> None:
        """Every member of the enum, because un-assigning one would be the worst outcome here."""
        criteria = Update20260908._legacy_marker_criteria(SPECIAL_TYPE_KEY)

        assert _matches(criteria, {SPECIAL_TYPE_KEY: flavour}) is False


class TestTheQueriesAreTheMigration:
    """Both collections are normalised with their own key and the same target value."""

    def test_each_collection_is_filtered_on_its_own_key(self) -> None:
        """The types and the objects name the marker through different enums."""
        updater = build_stubbed_updater(Update20260908)

        updater.start_update()

        type_criteria = updater.types_manager.update_many.call_args.kwargs['criteria']
        object_criteria = updater.objects_manager.update_many.call_args.kwargs['criteria']

        assert type_criteria == Update20260908._legacy_marker_criteria(TypeSchemaKey.SPECIAL_TYPE.value)
        assert object_criteria == Update20260908._legacy_marker_criteria(CmdbObjectKey.SPECIAL_TYPE.value)

    def test_null_is_what_is_written(self) -> None:
        """The value the model, the schemas and every write path since 20260417 use."""
        updater = build_stubbed_updater(Update20260908)

        updater.start_update()

        assert updater.types_manager.update_many.call_args.kwargs['update'] == {
            TypeSchemaKey.SPECIAL_TYPE.value: None
        }
        assert updater.objects_manager.update_many.call_args.kwargs['update'] == {
            CmdbObjectKey.SPECIAL_TYPE.value: None
        }
        assert NO_SPECIAL_TYPE is None


class TestMetadata:
    """The two values the runner reads before deciding to run anything."""

    def test_creation_date_is_the_registered_version(self) -> None:
        """It must equal the version registered in DatabaseUpdater.__UPDATE_VERSIONS__."""
        assert build_stubbed_updater(Update20260908).creation_date() == CREATION_DATE

    def test_the_description_names_both_states_it_normalises(self) -> None:
        """It is user-facing - the runner prints it per migration."""
        description = build_stubbed_updater(Update20260908).description()

        assert 'special_type' in description
        assert 'null' in description.lower()
