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
Unit tests for IsmsRiskClass

Pure tests: no Mongo, no Flask. The model declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO (tests/unit/models/test_cmdb_dao_shared_document.py owns that machinery), so what is
pinned here is what remains this model's own:

  - **the key set IS the wire format.** ``RiskClassKey`` drives both directions now, so a key added to
    the enum and not to the schema - or the reverse - is a document the collection would reject or
    silently drop. The two are asserted against each other rather than against a hand-written list
  - **construction is keyword-only**, which is not a style choice: ``CmdbDAO.__new__`` validates
    ``public_id`` out of ``**kwargs`` and runs before ``__init__``, so a positional call fails with a
    missing-key error before the constructor is ever reached
  - **a risk class round-trips through its own schema**, including one carrying only the two required
    fields - the state the config wizard creates before an admin fills in the rest
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_risk_class import IsmsRiskClass
from cmdb.models.isms_model.isms_risk_class_constants import RiskClassKey
from cmdb.class_schema.isms_model.isms_risk_class_schema import get_isms_risk_class_schema
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_risk_class import IsmsRiskClassInitError, IsmsRiskClassToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 4
NAME: str = 'High'
COLOR: str = '#ff0000'
SORT: int = 3
DESCRIPTION: str = 'Anything above the acceptance threshold'


def _document(**overrides: Any) -> dict[str, Any]:
    """A stored IsmsRiskClass document, as the collection holds it."""
    document: dict[str, Any] = {
        RiskClassKey.PUBLIC_ID.value: PUBLIC_ID,
        RiskClassKey.NAME.value: NAME,
        RiskClassKey.COLOR.value: COLOR,
        RiskClassKey.SORT.value: SORT,
        RiskClassKey.DESCRIPTION.value: DESCRIPTION,
    }
    document.update(overrides)

    return document


# -------------------------------------------------------------------------------------------------------------------- #
class TestTheKeySet:
    """RiskClassKey is the one place the document's shape is written down."""

    def test_the_schema_accepts_exactly_the_declared_keys(self) -> None:
        """
        The enum and the Cerberus schema describe the same document

        They are built from the same enum now, so this fails only if someone adds a key to one of them
        by hand - which is how a document that the collection rejects, or a field that silently never
        persists, gets written.
        """
        assert set(get_isms_risk_class_schema()) == {key.value for key in RiskClassKey}

    def test_the_model_drives_its_document_off_the_enum(self) -> None:
        """KEYS is what the shared from_data / to_json read, so the wiring is asserted directly"""
        assert IsmsRiskClass.KEYS is RiskClassKey


class TestConstruction:
    """What a caller may and may not do."""

    def test_the_optional_fields_default_to_none(self) -> None:
        """A class created with only its two required fields is legitimate"""
        risk_class = IsmsRiskClass(public_id=PUBLIC_ID, name=NAME, color=COLOR)

        assert (risk_class.sort, risk_class.description) == (None, None)

    def test_a_positional_call_is_refused_before_the_constructor(self) -> None:
        """
        Keyword-only, and the refusal comes from CmdbDAO rather than from the signature

        `CmdbDAO.__new__` validates the init keys against the KEYWORD arguments and runs first, so a
        positional call never reaches `__init__` at all - it fails on a public_id it cannot see. The
        signature used to advertise a positional call that could never have worked.
        """
        with pytest.raises(RequiredInitKeyNotFoundError):
            IsmsRiskClass(PUBLIC_ID, NAME, COLOR)  # pylint: disable=too-many-function-args

    def test_a_missing_public_id_is_refused(self) -> None:
        """public_id is a SUPER_INIT_KEY, checked against the keywords before __init__ runs"""
        with pytest.raises(RequiredInitKeyNotFoundError):
            IsmsRiskClass(name=NAME, color=COLOR)

    def test_an_init_failure_surfaces_as_the_models_error(self) -> None:
        """The one except arm this model still owns"""
        class _Exploding:
            """A value whose assignment is fine but whose public_id read is not"""

        with pytest.raises(IsmsRiskClassInitError):
            IsmsRiskClass(public_id=_Exploding(), name=NAME, color=COLOR)


class TestTheDocumentRoundTrip:
    """from_data / to_json, inherited but exercised through this model's keys."""

    def test_a_stored_document_round_trips(self) -> None:
        """Every key survives both directions unchanged"""
        assert IsmsRiskClass.to_json(IsmsRiskClass.from_data(_document())) == _document()

    def test_absent_optionals_read_as_none(self) -> None:
        """A document written before `sort` / `description` existed still loads"""
        minimal = {
            RiskClassKey.PUBLIC_ID.value: PUBLIC_ID,
            RiskClassKey.NAME.value: NAME,
            RiskClassKey.COLOR.value: COLOR,
        }

        risk_class = IsmsRiskClass.from_data(minimal)

        assert (risk_class.sort, risk_class.description) == (None, None)

    def test_a_document_missing_a_required_key_loads_as_none(self) -> None:
        """
        Current behaviour, pinned as it is: a document with no colour loads with `color: None`

        The shared `from_data` refuses a document missing a REQUIRED_INIT_KEY, and this model declares
        none - unlike IsmsImpact and IsmsLikelihood, which list their required keys for exactly this
        reason. The Cerberus schema says `color` is required and non-empty, so what loads here cannot
        be written back: the read is laxer than the write. Open question rather than a decision (see
        the sweep notes); this test will fail the moment REQUIRED_INIT_KEYS is declared, which is the
        point.
        """
        broken = _document()
        broken.pop(RiskClassKey.COLOR.value)

        loaded = IsmsRiskClass.from_data(broken)

        assert loaded.color is None
        assert Validator(get_isms_risk_class_schema()).validate(IsmsRiskClass.to_json(loaded)) is False

    def test_serialising_something_that_is_not_a_risk_class_is_refused(self) -> None:
        """
        The guard the migration buys: the shared to_json type-checks its instance

        It is what caught a live impact/likelihood and threat/vulnerability mix-up when those models
        migrated - two structural twins serialising cleanly as each other.
        """
        with pytest.raises(IsmsRiskClassToJsonError):
            IsmsRiskClass.to_json(object())  # type: ignore[arg-type]


class TestTheSchema:
    """What the collection will accept."""

    def test_a_full_document_validates(self) -> None:
        """The ordinary case"""
        assert Validator(get_isms_risk_class_schema()).validate(_document()) is True

    def test_the_two_required_fields_are_required(self) -> None:
        """A class without a name or a colour cannot be rendered at all"""
        validator = Validator(get_isms_risk_class_schema())

        assert validator.validate({RiskClassKey.PUBLIC_ID.value: PUBLIC_ID}) is False
        assert set(validator.errors) == {RiskClassKey.NAME.value, RiskClassKey.COLOR.value}

    def test_an_empty_name_or_colour_is_refused(self) -> None:
        """Empty strings would render as an unlabelled, invisible band"""
        validator = Validator(get_isms_risk_class_schema())

        assert validator.validate(_document(name='', color='')) is False

    def test_the_model_is_a_cmdb_dao(self) -> None:
        """The shared document machinery only applies to CmdbDAO subclasses"""
        assert issubclass(IsmsRiskClass, CmdbDAO)
