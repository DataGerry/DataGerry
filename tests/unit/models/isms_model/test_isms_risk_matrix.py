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
Unit tests for IsmsRiskMatrix

Pure tests: no Mongo, no Flask. The model declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO (tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is
pinned here is what remains this model's own:

  - **the grid is never None.** Every reader indexes ``risk_matrix`` as a list - the transfer helper,
    the self-heal's cell count, the config wizard's completeness check - and a matrix whose scales are
    not configured yet legitimately has no cells. An absent key reads as ``[]``
  - **the document the first boot writes passes its own schema.** The seeded default carries
    ``matrix_unit: None``, which the schema used to reject outright; the same null is what ``to_json``
    writes for an unset unit, so the two halves have to agree
  - **the singleton requires nothing beyond its public_id**, which is why REQUIRED_INIT_KEYS stays
    empty here while the impact category declares its name
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_risk_matrix import IsmsRiskMatrix
from cmdb.models.isms_model.isms_risk_matrix_constants import (
    RISK_MATRIX_PUBLIC_ID,
    UNASSIGNED_RISK_CLASS_ID,
    RiskMatrixCellKey,
    RiskMatrixKey,
)
from cmdb.class_schema.isms_model.isms_risk_matrix_schema import get_isms_risk_matrix_schema
from cmdb.database.predefined_data.isms_data import get_default_risk_matrix
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_risk_matrix import IsmsRiskMatrixInitError, IsmsRiskMatrixToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

MATRIX_UNIT: str = 'EUR'


def _cell(impact_id: int = 1, likelihood_id: int = 2) -> dict[str, Any]:
    """One cell of the grid, as the generator writes it."""
    return {
        RiskMatrixCellKey.ROW.value: 0,
        RiskMatrixCellKey.COLUMN.value: 0,
        RiskMatrixCellKey.IMPACT_ID.value: impact_id,
        RiskMatrixCellKey.IMPACT_VALUE.value: 2.0,
        RiskMatrixCellKey.LIKELIHOOD_ID.value: likelihood_id,
        RiskMatrixCellKey.LIKELIHOOD_VALUE.value: 3.0,
        RiskMatrixCellKey.CALCULATED_VALUE.value: 6.0,
        RiskMatrixCellKey.RISK_CLASS_ID.value: UNASSIGNED_RISK_CLASS_ID,
    }


def _document(**overrides: Any) -> dict[str, Any]:
    """The stored singleton, as the collection holds it."""
    document: dict[str, Any] = {
        RiskMatrixKey.PUBLIC_ID.value: RISK_MATRIX_PUBLIC_ID,
        RiskMatrixKey.RISK_MATRIX.value: [_cell()],
        RiskMatrixKey.MATRIX_UNIT.value: MATRIX_UNIT,
    }
    document.update(overrides)

    return document


# -------------------------------------------------------------------------------------------------------------------- #
class TestTheKeySets:
    """The document's keys and the cell's keys, one enum each."""

    def test_the_schema_accepts_exactly_the_document_keys(self) -> None:
        """A key in one and not the other is a field that never persists, or a rejected document"""
        assert set(get_isms_risk_matrix_schema()) == {key.value for key in RiskMatrixKey}

    def test_the_cell_schema_accepts_exactly_the_cell_keys(self) -> None:
        """The grid's entries have their own shape, written down once"""
        cell_schema = get_isms_risk_matrix_schema()[RiskMatrixKey.RISK_MATRIX.value]['schema']['schema']

        assert set(cell_schema) == {key.value for key in RiskMatrixCellKey}

    def test_the_document_keys_live_in_the_model_layer(self) -> None:
        """
        Where the enum is defined is the point of this move

        It used to live in `cmdb/database/predefined_data/`, so the model layer imported its own
        document shape from the seeding package; the seed data now imports it from here instead.
        """
        assert RiskMatrixKey.__module__ == 'cmdb.models.isms_model.isms_risk_matrix_constants'


class TestConstruction:
    """What a caller may and may not do."""

    def test_an_absent_grid_becomes_empty(self) -> None:
        """Every reader indexes the grid as a list, and no scales means no cells"""
        matrix = IsmsRiskMatrix(public_id=RISK_MATRIX_PUBLIC_ID)

        assert matrix.risk_matrix == []

    def test_a_positional_call_is_refused_before_the_constructor(self) -> None:
        """
        Keyword-only: CmdbDAO.__new__ validates the init keys against the KEYWORD arguments and runs
        first, so a positional call fails on a public_id it cannot see
        """
        with pytest.raises(RequiredInitKeyNotFoundError):
            IsmsRiskMatrix(RISK_MATRIX_PUBLIC_ID, [])  # pylint: disable=too-many-function-args

    def test_an_init_failure_surfaces_as_the_models_error(self) -> None:
        """The one except arm this model still owns"""
        class _Exploding:
            """A public_id the DAO cannot work with"""

        with pytest.raises(IsmsRiskMatrixInitError):
            IsmsRiskMatrix(public_id=_Exploding())


class TestTheDocumentRoundTrip:
    """from_data / to_json, inherited but exercised through this model's keys."""

    def test_a_stored_document_round_trips(self) -> None:
        """Every key survives both directions unchanged, cells included"""
        assert IsmsRiskMatrix.to_json(IsmsRiskMatrix.from_data(_document())) == _document()

    def test_a_document_without_a_grid_round_trips_validly(self) -> None:
        """
        The read/write asymmetry this migration closed

        Such a document used to load as `risk_matrix: None` and serialise back into something the
        schema rejects - while every reader indexed it as a list.
        """
        legacy = _document()
        legacy.pop(RiskMatrixKey.RISK_MATRIX.value)

        written = IsmsRiskMatrix.to_json(IsmsRiskMatrix.from_data(legacy))

        assert written[RiskMatrixKey.RISK_MATRIX.value] == []
        assert Validator(get_isms_risk_matrix_schema()).validate(written) is True

    def test_serialising_something_that_is_not_a_matrix_is_refused(self) -> None:
        """The guard the migration buys: the shared to_json type-checks its instance"""
        with pytest.raises(IsmsRiskMatrixToJsonError):
            IsmsRiskMatrix.to_json(object())  # type: ignore[arg-type]


class TestTheSchema:
    """What the collection will accept."""

    def test_a_full_document_validates(self) -> None:
        """The ordinary case"""
        assert Validator(get_isms_risk_matrix_schema()).validate(_document()) is True

    def test_the_seeded_default_validates(self) -> None:
        """
        The document the FIRST BOOT writes must pass the schema of the collection it goes into

        It did not: the default carries `matrix_unit: None` and the key was not nullable, so the one
        document every installation starts with was invalid against its own definition.
        """
        seeded = {
            key.value if isinstance(key, RiskMatrixKey) else key: value
            for key, value in get_default_risk_matrix().items()
        }

        assert Validator(get_isms_risk_matrix_schema()).validate(seeded) is True

    def test_an_unset_unit_is_accepted(self) -> None:
        """`to_json` writes null for a matrix whose unit an admin never set"""
        assert Validator(get_isms_risk_matrix_schema()).validate(_document(matrix_unit=None)) is True

    def test_a_cell_needs_numeric_coordinates(self) -> None:
        """A cell addresses a grid position, so text there is a broken cell"""
        broken = _document(risk_matrix=[{**_cell(), RiskMatrixCellKey.ROW.value: 'first'}])

        assert Validator(get_isms_risk_matrix_schema()).validate(broken) is False

    def test_the_model_is_a_cmdb_dao(self) -> None:
        """The shared document machinery only applies to CmdbDAO subclasses"""
        assert issubclass(IsmsRiskMatrix, CmdbDAO)
