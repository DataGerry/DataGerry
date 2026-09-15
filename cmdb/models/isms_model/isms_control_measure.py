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
Implementation of IsmsControlMeasure in DataGerry - ISMS

An IsmsControlMeasure is one control, requirement or measure of the ISMS (collection
``isms.controlMeasure``). It is the catalogue entry an IsmsControlMeasureAssignment attaches to a risk
assessment, and the row the Statement of Applicability report is built from. Three properties of this
document are worth knowing before changing it:

**Its key set is closed.** ``ControlMeasureKey`` names every persisted key, and ``from_data`` /
``to_json`` are a round-trip over exactly that set. The write routes validate against ``SCHEMA`` with
``purge_unknown=True``, so an undeclared key cannot be stored in the first place.

**``source`` and ``implementation_state`` are references, not text.** Both hold the public_id of a
``CmdbExtendableOption`` - of option type ``CONTROL_MEASURE`` and ``IMPLEMENTATION_STATE`` respectively
- which the SoA report resolves to the option's value. The CSV importer accepts the option *label* and
resolves it to the id before a document is written.

**``is_applicable`` is a two-state answer, never three.** It is the Statement of Applicability's own
field, and a null there is not a third state: the report renders one as an empty cell while a stored
False renders as "No", and the CSV importer has always written False for an empty cell. The Cerberus
schema still accepts null on write (tightening it would change the write contract), so ``from_data``
normalises a missing or null value to False - which is what the ``is_applicable`` default meant all
along, and could never do while every read passed the key explicitly

``control_measure_type`` holds the raw ``ControlMeasureType`` value rather than a member: the value is
pinned by the schema's ``allowed`` list, so validation - not the model - is what refuses an unknown
type. The attribute is annotated as the primitive it actually holds
"""
from typing import Any

from cmdb.class_schema.isms_model.isms_control_measure_schema import get_isms_control_measure_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey

from cmdb.errors.models.isms_control_measure import (
    IsmsControlMeasureInitError,
    IsmsControlMeasureInitFromDataError,
    IsmsControlMeasureToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                              IsmsControlMeasure - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsControlMeasure(CmdbDAO):
    """
    Implementation of IsmsControlMeasure which represents a control measure in ISMS

    Extends: CmdbDAO
    """
    COLLECTION = "isms.controlMeasure"

    INDEX_KEYS: list[dict[str, Any]] = [
        # Not read by any backend query: the SoA report resolves types in memory. It serves the client
        # driven '?filter=' / '?sort=' on the list route, where control_measure_type is a table column
        {
            'keys': [(ControlMeasureKey.CONTROL_MEASURE_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': 'control_measure_type',
            'unique': False,
        },
    ]

    SCHEMA: dict = get_isms_control_measure_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither;
    # the is_applicable rule below travels as the normalize_document hook
    KEYS = ControlMeasureKey
    INIT_FROM_DATA_ERROR = IsmsControlMeasureInitFromDataError
    TO_JSON_ERROR = IsmsControlMeasureToJsonError

    # R0913 stays: ten fields, all flat and independent, so grouping them into a parameter object would
    # only move the same names one level down. R0917 does not apply - the signature is keyword-only,
    # which it must be: CmdbDAO.__new__ requires public_id in **kwargs, so a positional call fails with
    # 'A required InitKey is missing: public_id!' before __init__ ever runs
    # pylint: disable=R0913
    def __init__(
            self,
            *,
            public_id: int,
            title: str,
            control_measure_type: str,
            source: int,
            implementation_state: int,
            identifier: str = None,
            chapter: str = None,
            description: str = None,
            is_applicable: bool = False,
            reason: str = None
        ) -> None:
        """
        Initialises an IsmsControlMeasure

        Args:
            public_id (int): public_id of the IsmsControlMeasure
            title (str): The title of the IsmsControlMeasure
            control_measure_type (str): A ControlMeasureType value of the IsmsControlMeasure
            source (int): public_id of CmdbExtendableOption('CONTROL_MEASURE') of the IsmsControlMeasure
            implementation_state (int): public_id of CmdbExtendableOption('IMPLEMENTATION_STATE')
                                        of the IsmsControlMeasure
            identifier (str, optional): The identifier of the IsmsControlMeasure
            chapter (str, optional): The chapter of the IsmsControlMeasure
            description (str, optional): The description of the IsmsControlMeasure
            is_applicable (bool): If True then the IsmsControlMeasure is applicable. Defaults to False
            reason (str, optional): The reason of the IsmsControlMeasure

        Raises:
            IsmsControlMeasureInitError: If the IsmsControlMeasure could not be initialised
        """
        try:
            self.title = title
            self.control_measure_type = control_measure_type
            self.source = source
            self.implementation_state = implementation_state
            self.identifier = identifier
            self.chapter = chapter
            self.description = description
            self.is_applicable = is_applicable
            self.reason = reason

            super().__init__(public_id = public_id)
        except Exception as err:
            raise IsmsControlMeasureInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Normalises the Statement of Applicability answer of a document IN PLACE

        A missing or null value means "not applicable", never a third state - see the module docstring.
        Called by the shared ``CmdbDAO.from_data``, and directly by the two readers that never build a
        model instance: the insert route, which writes the validated payload straight to the collection,
        and the SoA report, which reads raw documents

        Args:
            data (dict[str, Any]): A control-measure document or validated payload, edited in place
        """
        data[ControlMeasureKey.IS_APPLICABLE.value] = bool(data.get(ControlMeasureKey.IS_APPLICABLE.value))


    @classmethod
    def normalize_is_applicable(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Normalises the SoA answer of a document and returns it, for a caller that wants the dict back

        The one-expression wrapper around ``normalize_document`` that lets a call sit inline where the
        document is being handed on, as in ``insert_item(IsmsControlMeasure.normalize_is_applicable(data))``

        Args:
            data (dict[str, Any]): A control-measure document or validated payload, edited in place

        Returns:
            dict[str, Any]: The same dict, with 'is_applicable' set to a boolean
        """
        cls.normalize_document(data)

        return data
