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
Unit tests for IsmsProtectionGoal

Pure tests: no Mongo, no Flask. The model declares ``KEYS`` and inherits ``from_data`` / ``to_json``
from CmdbDAO, whose shared machinery has its own tests, so what is
pinned here is what remains this model's own:

  - **``predefined`` is two-state, never null.** The schema takes a boolean, but the shared
    ``from_data`` reads with ``data.get()`` - so a goal stored without the flag would load as None
    and serialise into a document its own schema rejects. It is coerced instead, which is what the
    absence means: a goal DataGerry did not seed is user-created
  - **the three seeded goals validate against the schema they are written into**, asserted against
    ``get_default_protection_goals()`` itself rather than a copy of it
  - **a document without a name is refused on read**, through REQUIRED_INIT_KEYS
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_protection_goal import IsmsProtectionGoal
from cmdb.models.isms_model.isms_protection_goal_constants import (
    PROTECTION_GOAL_REQUIRED_DOCUMENT_KEYS,
    ProtectionGoalKey,
)
from cmdb.class_schema.isms_model.isms_protection_goal_schema import get_isms_protection_goal_schema
from cmdb.database.predefined_data.isms_data import get_default_protection_goals
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.isms_protection_goal import (
    IsmsProtectionGoalInitError,
    IsmsProtectionGoalInitFromDataError,
    IsmsProtectionGoalToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 7
NAME: str = 'Confidentiality'


def _document(**overrides: Any) -> dict[str, Any]:
    """A stored IsmsProtectionGoal document, as the collection holds it."""
    document: dict[str, Any] = {
        ProtectionGoalKey.PUBLIC_ID.value: PUBLIC_ID,
        ProtectionGoalKey.NAME.value: NAME,
        ProtectionGoalKey.PREDEFINED.value: True,
    }
    document.update(overrides)

    return document


# -------------------------------------------------------------------------------------------------------------------- #
class TestTheKeySet:
    """ProtectionGoalKey is the one place the document's shape is written down."""

    def test_the_schema_accepts_exactly_the_declared_keys(self) -> None:
        """A key in one and not the other is a field that never persists, or a rejected document"""
        assert set(get_isms_protection_goal_schema()) == {key.value for key in ProtectionGoalKey}

    def test_the_keys_live_in_the_model_layer(self) -> None:
        """
        Where the enum is defined is half the point of this migration

        Keeping it in the seed package beside the three goals DataGerry writes makes the model
        have imported its own document shape from `cmdb.database`; the seed data imports it from here
        instead.
        """
        assert ProtectionGoalKey.__module__ == 'cmdb.models.isms_model.isms_protection_goal_constants'

    def test_only_the_name_is_required_on_read(self) -> None:
        """`predefined` is coerced rather than required - its absence has a meaning, not a gap"""
        assert PROTECTION_GOAL_REQUIRED_DOCUMENT_KEYS == [ProtectionGoalKey.NAME.value]


class TestThePredefinedFlag:
    """Two states, and every way of not saying so means False."""

    @pytest.mark.parametrize('stored', [None, False, 0, ''], ids=['null', 'false', 'zero', 'empty'])
    def test_anything_unset_reads_as_not_predefined(self, stored: Any) -> None:
        """A goal nobody marked as seeded is user-created"""
        goal = IsmsProtectionGoal(public_id=PUBLIC_ID, name=NAME, predefined=stored)

        assert goal.predefined is False

    def test_an_absent_flag_reads_as_not_predefined(self) -> None:
        """
        The case that produced an invalid document

        The shared `from_data` passes `data.get('predefined')`, so the constructor's default never
        applied: the goal loaded with None and `to_json` wrote a null the schema rejects.
        """
        legacy = _document()
        legacy.pop(ProtectionGoalKey.PREDEFINED.value)

        written = IsmsProtectionGoal.to_json(IsmsProtectionGoal.from_data(legacy))

        assert written[ProtectionGoalKey.PREDEFINED.value] is False
        assert Validator(get_isms_protection_goal_schema()).validate(written) is True

    def test_a_seeded_goal_keeps_its_flag(self) -> None:
        """The flag is what the routes refuse to delete or rename on, so it must survive a round trip"""
        assert IsmsProtectionGoal.from_data(_document()).predefined is True


class TestConstruction:
    """What a caller may and may not do."""

    def test_a_positional_call_is_refused_before_the_constructor(self) -> None:
        """
        Keyword-only: CmdbDAO.__new__ validates the init keys against the KEYWORD arguments and runs
        first, so a positional call fails on a public_id it cannot see
        """
        with pytest.raises(RequiredInitKeyNotFoundError):
            IsmsProtectionGoal(PUBLIC_ID, NAME)  # pylint: disable=too-many-function-args

    def test_an_init_failure_surfaces_as_the_models_error(self) -> None:
        """The one except arm this model still owns"""
        class _Exploding:
            """A public_id the DAO cannot work with"""

        with pytest.raises(IsmsProtectionGoalInitError):
            IsmsProtectionGoal(public_id=_Exploding(), name=NAME)


class TestTheDocumentRoundTrip:
    """from_data / to_json, inherited but exercised through this model's keys."""

    def test_a_stored_document_round_trips(self) -> None:
        """Every key survives both directions unchanged"""
        assert IsmsProtectionGoal.to_json(IsmsProtectionGoal.from_data(_document())) == _document()

    def test_a_document_without_a_name_is_refused(self) -> None:
        """REQUIRED_INIT_KEYS: a nameless goal cannot be written back, so it is not read in"""
        nameless = _document()
        nameless.pop(ProtectionGoalKey.NAME.value)

        with pytest.raises(IsmsProtectionGoalInitFromDataError):
            IsmsProtectionGoal.from_data(nameless)

    def test_serialising_something_that_is_not_a_goal_is_refused(self) -> None:
        """The guard the migration buys: the shared to_json type-checks its instance"""
        with pytest.raises(IsmsProtectionGoalToJsonError):
            IsmsProtectionGoal.to_json(object())  # type: ignore[arg-type]


class TestTheSchema:
    """What the collection will accept."""

    def test_the_seeded_goals_validate(self) -> None:
        """The three documents every installation starts with, checked against their own definition"""
        validator = Validator(get_isms_protection_goal_schema())

        for goal in get_default_protection_goals():
            document = {
                key.value if isinstance(key, ProtectionGoalKey) else key: value
                for key, value in goal.items()
            }

            assert validator.validate(document) is True, validator.errors

    def test_a_nameless_document_is_refused(self) -> None:
        """The one required text field"""
        nameless = _document()
        nameless.pop(ProtectionGoalKey.NAME.value)

        assert Validator(get_isms_protection_goal_schema()).validate(nameless) is False

    def test_a_non_boolean_flag_is_refused(self) -> None:
        """The flag is two-state on the wire as well"""
        assert Validator(get_isms_protection_goal_schema()).validate(_document(predefined='yes')) is False

    def test_the_model_is_a_cmdb_dao(self) -> None:
        """The shared document machinery only applies to CmdbDAO subclasses"""
        assert issubclass(IsmsProtectionGoal, CmdbDAO)
