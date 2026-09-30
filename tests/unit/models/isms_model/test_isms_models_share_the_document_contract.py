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
The document contract every ISMS entity model shares

Every ISMS entity reads and writes through ``CmdbDAO``'s shared ``from_data`` / ``to_json`` over its key
enum, and every one reads as strictly as its schema writes: a key the schema requires is one the model
refuses to load a document without - so a document the model loads is one the schema would accept
back. Three kinds of exception are deliberate, and pinned here by name so a new one has to be argued:

* a **two-state flag whose absence means False** is not required on a read - protection goal
  ``predefined`` (a goal DataGerry did not seed), control measure ``is_applicable`` (never a third state)
* the **two models whose schema requires every key** are read by their identity only - risk assessment
  (the risk and the assessed object) and control-measure assignment (the measure and the assessment).
  A list route reads every row through the model, so requiring all of them would let one incomplete
  row fail the whole page
"""
import pytest

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsControlMeasureAssignment,
    IsmsImpact,
    IsmsImpactCategory,
    IsmsLikelihood,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsRiskAssessment,
    IsmsRiskClass,
    IsmsRiskMatrix,
    IsmsThreat,
    IsmsVulnerability,
)
from cmdb.models.isms_model.isms_control_measure_assignment_constants import (
    CONTROL_MEASURE_ASSIGNMENT_REQUIRED_DOCUMENT_KEYS,
)
from cmdb.models.isms_model.isms_risk_assessment_constants import RISK_ASSESSMENT_REQUIRED_DOCUMENT_KEYS
# -------------------------------------------------------------------------------------------------------------------- #

ISMS_MODELS: list[type[CmdbDAO]] = [
    IsmsControlMeasure, IsmsControlMeasureAssignment, IsmsImpact, IsmsImpactCategory, IsmsLikelihood,
    IsmsProtectionGoal, IsmsRisk, IsmsRiskAssessment, IsmsRiskClass, IsmsRiskMatrix, IsmsThreat,
    IsmsVulnerability,
]

# Schema-required keys a model deliberately does not require on a read: a two-state flag whose absence
# means False
ABSENT_MEANS_FALSE: dict[type[CmdbDAO], set[str]] = {
    IsmsProtectionGoal: {'predefined'},
    IsmsControlMeasure: {'is_applicable'},
}

# Models whose schema requires every key, read by their identity only
IDENTITY_ONLY: dict[type[CmdbDAO], list[str]] = {
    IsmsRiskAssessment: RISK_ASSESSMENT_REQUIRED_DOCUMENT_KEYS,
    IsmsControlMeasureAssignment: CONTROL_MEASURE_ASSIGNMENT_REQUIRED_DOCUMENT_KEYS,
}

MODEL_IDS: list[str] = [model.__name__ for model in ISMS_MODELS]


def _schema_required(model: type[CmdbDAO]) -> set[str]:
    """The keys the model's Cerberus schema requires on a write."""
    return {key for key, rule in model.SCHEMA.items() if rule.get('required')}


@pytest.mark.parametrize('model', ISMS_MODELS, ids=MODEL_IDS)
def test_the_model_shares_the_document_pair(model: type[CmdbDAO]) -> None:
    """A key enum and no hand-written pair: the enum is the one place the document shape is stated."""
    assert model.KEYS is not None
    assert 'from_data' not in vars(model)
    assert 'to_json' not in vars(model)


@pytest.mark.parametrize('model', ISMS_MODELS, ids=MODEL_IDS)
def test_a_required_read_key_is_one_the_schema_requires(model: type[CmdbDAO]) -> None:
    """The read is never stricter than the write - a stored, valid document always loads."""
    assert set(model.REQUIRED_INIT_KEYS) <= _schema_required(model)


@pytest.mark.parametrize('model', [model for model in ISMS_MODELS if model not in IDENTITY_ONLY],
                         ids=[model.__name__ for model in ISMS_MODELS if model not in IDENTITY_ONLY])
def test_the_read_is_as_strict_as_the_write(model: type[CmdbDAO]) -> None:
    """Every schema-required key is required on a read too, except a named absent-means-False flag."""
    assert _schema_required(model) - set(model.REQUIRED_INIT_KEYS) == ABSENT_MEANS_FALSE.get(model, set())


@pytest.mark.parametrize('model', list(IDENTITY_ONLY), ids=[model.__name__ for model in IDENTITY_ONLY])
def test_an_every_key_schema_is_read_by_its_identity(model: type[CmdbDAO]) -> None:
    """The two models whose schema requires everything require exactly their identity on a read."""
    assert model.REQUIRED_INIT_KEYS == IDENTITY_ONLY[model]
