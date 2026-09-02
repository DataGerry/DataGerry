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
Unit tests for cmdb.framework.extendable_option_references

Pure tests with a mocked MongoDatabaseManager. Three things are worth pinning here:

* the map itself - every entry names a real collection and a field the referencing model actually
  carries, checked against the model classes rather than against string literals
* the existence check short-circuits, both across collections and inside the count
* the re-pointing of an ARRAY reference, which needs two statements in a fixed order ($addToSet the
  keeper first, $pull the discarded id second) so an interruption can never lose the reference. This
  is the part a scalar-only implementation would silently get wrong
"""
from unittest.mock import MagicMock

import pytest

from cmdb.models.extendable_option_model import OptionType
from cmdb.models.isms_model.isms_threat import IsmsThreat
from cmdb.models.isms_model.isms_vulnerability import IsmsVulnerability
from cmdb.models.isms_model.isms_risk import IsmsRisk
from cmdb.models.isms_model.isms_control_measure import IsmsControlMeasure
from cmdb.models.isms_model.isms_risk_assessment import IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment import IsmsControlMeasureAssignment
from cmdb.models.object_group_model.cmdb_object_group import CmdbObjectGroup
from cmdb.models.port_model import CmdbPort, PortKey, PORT_SELECT_FIELD_OPTION_TYPES
from cmdb.framework.extendable_options.extendable_option_references import (
    EXTENDABLE_OPTION_REFERENCES,
    EXISTENCE_CHECK_LIMIT,
    ExtendableOptionReference,
    ExtendableOptionUsageField,
    get_option_references,
    is_option_referenced,
    repoint_option_references,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'
OPTION_ID: int = 41
KEEPER_ID: int = 12


def _dbm(counts_by_collection: dict[str, int] | None = None, modified: int = 0) -> MagicMock:
    """Builds a MongoDatabaseManager mock whose count and update results are configurable."""
    counts = counts_by_collection or {}
    dbm = MagicMock(name='dbm')
    dbm.count.side_effect = lambda collection, _db, _criteria, limit=None: counts.get(collection, 0)
    dbm.update_many.return_value = MagicMock(modified_count=modified)
    dbm.update_many_pull.return_value = MagicMock(modified_count=modified)

    return dbm


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the map itself                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheReferenceMap:
    """Every entry has to name a collection and a field that really exist."""

    @pytest.mark.parametrize('option_type, expected', [
        (OptionType.THREAT_VULNERABILITY, {
            (IsmsThreat.COLLECTION, ExtendableOptionUsageField.SOURCE.value),
            (IsmsVulnerability.COLLECTION, ExtendableOptionUsageField.SOURCE.value),
        }),
        (OptionType.OBJECT_GROUP, {
            (CmdbObjectGroup.COLLECTION, ExtendableOptionUsageField.CATEGORIES.value),
        }),
        (OptionType.CONTROL_MEASURE, {
            (IsmsControlMeasure.COLLECTION, ExtendableOptionUsageField.SOURCE.value),
        }),
        (OptionType.IMPLEMENTATION_STATE, {
            (IsmsControlMeasure.COLLECTION, ExtendableOptionUsageField.IMPLEMENTATION_STATE.value),
            (IsmsRiskAssessment.COLLECTION, ExtendableOptionUsageField.IMPLEMENTATION_STATUS.value),
            (IsmsControlMeasureAssignment.COLLECTION, ExtendableOptionUsageField.IMPLEMENTATION_STATUS.value),
        }),
        (OptionType.RISK, {
            (IsmsRisk.COLLECTION, ExtendableOptionUsageField.CATEGORY_ID.value),
        }),
        (OptionType.PORT_STATUS, {(CmdbPort.COLLECTION, PortKey.STATUS.value)}),
        (OptionType.PORT_TYPE, {(CmdbPort.COLLECTION, PortKey.PORT_TYPE.value)}),
        (OptionType.PORT_SPEED, {(CmdbPort.COLLECTION, PortKey.SPEED.value)}),
    ], ids=lambda value: value.value if isinstance(value, OptionType) else '')
    def test_references_of_an_option_type(self, option_type: OptionType, expected: set) -> None:
        """The declared references of each OptionType, as (collection, field) pairs."""
        assert {(reference.collection, reference.field)
                for reference in get_option_references(option_type)} == expected

    def test_only_the_object_group_reference_is_an_array(self) -> None:
        """'categories' is the one list-of-ids reference; treating another as scalar would drop data."""
        array_references: set[tuple[str, str]] = {
            (reference.collection, reference.field)
            for references in EXTENDABLE_OPTION_REFERENCES.values()
            for reference in references
            if reference.is_array
        }

        assert array_references == {
            (CmdbObjectGroup.COLLECTION, ExtendableOptionUsageField.CATEGORIES.value),
        }

    def test_a_reference_is_scalar_by_default(self) -> None:
        """The is_array flag has to be opted into, so a new scalar entry cannot be got wrong."""
        assert ExtendableOptionReference('some.collection', 'some_field').is_array is False

    def test_the_port_references_are_derived_from_the_port_model(self) -> None:
        """The port entries restate nothing: they are built from the model's own select-field map.

        A port select field added there is referenced here automatically, so the two cannot drift."""
        for field, option_type in PORT_SELECT_FIELD_OPTION_TYPES.items():
            assert get_option_references(option_type) == (
                ExtendableOptionReference(CmdbPort.COLLECTION, field.value),
            )

    def test_the_cable_type_is_not_referenced_yet(self) -> None:
        """CABLE_TYPE lives on a connection, and framework.portConnections does not exist yet.

        The step that adds it has to register the reference here - this is the test that says so out
        loud."""
        assert get_option_references(OptionType.CABLE_TYPE) == ()

    def test_an_unknown_option_type_has_no_references(self) -> None:
        """A value that is not an OptionType at all resolves to an empty tuple, not a KeyError."""
        assert get_option_references('SOMETHING_ELSE') == ()

    def test_a_stored_string_resolves_like_the_enum_member(self) -> None:
        """A document read back from MongoDB carries the plain string, and must map to the same entry."""
        assert get_option_references(OptionType.RISK.value) == get_option_references(OptionType.RISK)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                is_option_referenced                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIsOptionReferenced:
    """The pre-delete existence check."""

    def test_true_when_a_referencing_document_exists(self) -> None:
        """One match in any referencing collection is enough."""
        dbm = _dbm({IsmsRisk.COLLECTION: 1})

        assert is_option_referenced(dbm, DB_NAME, OptionType.RISK, OPTION_ID) is True

    def test_false_when_nothing_references_the_option(self) -> None:
        """No match anywhere means the option is free to delete."""
        dbm = _dbm()

        assert is_option_referenced(dbm, DB_NAME, OptionType.IMPLEMENTATION_STATE, OPTION_ID) is False

    def test_counts_are_capped_at_one(self) -> None:
        """An existence check must not count every match in the collection."""
        dbm = _dbm()

        is_option_referenced(dbm, DB_NAME, OptionType.RISK, OPTION_ID)

        assert dbm.count.call_args.kwargs['limit'] == EXISTENCE_CHECK_LIMIT

    def test_stops_at_the_first_matching_collection(self) -> None:
        """A hit in the first collection makes the remaining ones pointless queries."""
        dbm = _dbm({IsmsControlMeasure.COLLECTION: 1})

        is_option_referenced(dbm, DB_NAME, OptionType.IMPLEMENTATION_STATE, OPTION_ID)

        assert dbm.count.call_count == 1

    def test_queries_every_collection_when_none_match(self) -> None:
        """All three IMPLEMENTATION_STATE collections are consulted before answering 'not used'."""
        dbm = _dbm()

        is_option_referenced(dbm, DB_NAME, OptionType.IMPLEMENTATION_STATE, OPTION_ID)

        assert dbm.count.call_count == 3

    def test_nothing_is_queried_for_an_unreferenced_option_type(self) -> None:
        """A CABLE_TYPE option costs no queries at all until connections exist."""
        dbm = _dbm()

        assert is_option_referenced(dbm, DB_NAME, OptionType.CABLE_TYPE, OPTION_ID) is False
        dbm.count.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              repoint_option_references                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRepointOptionReferences:
    """Moving the references of a discarded duplicate onto the keeper."""

    def test_scalar_reference_is_set_to_the_keeper(self) -> None:
        """A scalar field is a single $set from the old id to the new one."""
        dbm = _dbm(modified=2)

        modified: int = repoint_option_references(dbm, DB_NAME, OptionType.RISK, OPTION_ID, KEEPER_ID)

        dbm.update_many.assert_called_once_with(
            IsmsRisk.COLLECTION,
            DB_NAME,
            {ExtendableOptionUsageField.CATEGORY_ID.value: OPTION_ID},
            {ExtendableOptionUsageField.CATEGORY_ID.value: KEEPER_ID},
        )
        dbm.update_many_pull.assert_not_called()
        assert modified == 2

    def test_array_reference_adds_the_keeper_before_pulling_the_duplicate(self) -> None:
        """Keeper first: an interruption between the two must leave both ids, never neither."""
        dbm = _dbm(modified=1)
        calls: list[str] = []
        dbm.update_many.side_effect = lambda *args, **kwargs: (
            calls.append('addToSet'), MagicMock(modified_count=1),
        )[1]
        dbm.update_many_pull.side_effect = lambda *args, **kwargs: (
            calls.append('pull'), MagicMock(modified_count=1),
        )[1]

        repoint_option_references(dbm, DB_NAME, OptionType.OBJECT_GROUP, OPTION_ID, KEEPER_ID)

        assert calls == ['addToSet', 'pull']

    def test_array_reference_uses_add_to_set_and_pull_on_the_right_field(self) -> None:
        """The keeper is added without duplicating it, and only the discarded id is pulled."""
        dbm = _dbm(modified=1)

        repoint_option_references(dbm, DB_NAME, OptionType.OBJECT_GROUP, OPTION_ID, KEEPER_ID)

        dbm.update_many.assert_called_once_with(
            CmdbObjectGroup.COLLECTION,
            DB_NAME,
            {ExtendableOptionUsageField.CATEGORIES.value: OPTION_ID},
            {ExtendableOptionUsageField.CATEGORIES.value: KEEPER_ID},
            add_to_set=True,
        )
        dbm.update_many_pull.assert_called_once_with(
            CmdbObjectGroup.COLLECTION,
            DB_NAME,
            {ExtendableOptionUsageField.CATEGORIES.value: OPTION_ID},
            {ExtendableOptionUsageField.CATEGORIES.value: OPTION_ID},
        )

    def test_an_array_reference_reports_the_pull_count_only(self) -> None:
        """The $addToSet and the $pull touch the same documents - counting both would double it."""
        dbm = _dbm()
        dbm.update_many.return_value = MagicMock(modified_count=3)
        dbm.update_many_pull.return_value = MagicMock(modified_count=3)

        assert repoint_option_references(dbm, DB_NAME, OptionType.OBJECT_GROUP, OPTION_ID, KEEPER_ID) == 3

    def test_every_referencing_collection_is_rewritten(self) -> None:
        """An IMPLEMENTATION_STATE option is referenced from three collections, all of them updated."""
        dbm = _dbm(modified=1)

        modified: int = repoint_option_references(
            dbm, DB_NAME, OptionType.IMPLEMENTATION_STATE, OPTION_ID, KEEPER_ID,
        )

        assert dbm.update_many.call_count == 3
        assert modified == 3

    def test_nothing_is_written_for_an_unreferenced_option_type(self) -> None:
        """A CABLE_TYPE duplicate has no references to move yet."""
        dbm = _dbm()

        assert repoint_option_references(dbm, DB_NAME, OptionType.CABLE_TYPE, OPTION_ID, KEEPER_ID) == 0
        dbm.update_many.assert_not_called()

    def test_a_port_option_is_repointed_on_the_ports_collection(self) -> None:
        """A PORT_TYPE duplicate moves the ports that hold it, which is why step 3 registered it."""
        dbm = _dbm(modified=4)

        modified: int = repoint_option_references(dbm, DB_NAME, OptionType.PORT_TYPE, OPTION_ID, KEEPER_ID)

        dbm.update_many.assert_called_once_with(
            CmdbPort.COLLECTION,
            DB_NAME,
            {PortKey.PORT_TYPE.value: OPTION_ID},
            {PortKey.PORT_TYPE.value: KEEPER_ID},
        )
        assert modified == 4
