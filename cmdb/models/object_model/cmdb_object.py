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
Implementation of CmdbObject, the stored instance of a CmdbType and the core record of the CMDB

Every read, write, import, export, render and history entry in the framework passes through this
model (collection ``framework.objects``). Five properties govern any change here:

**A field entry is a name/value/type triple, and the name is its identity.** ``fields`` holds the
top-level entries and ``multi_data_sections`` the same shape nested one section and one row deep -
which is why ``CmdbObjectFieldKey`` applies to both. A field's ``name`` is immutable by contract: the
frontend does not allow renaming and every stored value is addressed by it, so a rename would orphan
the value on every object of the type.

**The lifecycle values are server-owned and never invented here.** The create route stamps
``creation_time`` and ``version``, the update route pins the stored creation time and stamps
``last_edit_time`` / ``editor_id``, and PATCH refuses all of them outright. The model therefore
reports what a document carries: an object without a creation time reads as None rather than as
*today*, which is what it used to become - differently on every read, because the default was
evaluated per call.

**A timestamp is a real date whichever shape it arrives in.** Both are declared in ``DATE_FIELDS``, so
the ``{'$date': ...}`` wrapper the frontend sends and a timestamp string from an API client are
normalised before the document is stored, and a value that cannot be read is refused rather than
guessed - it used to be parsed with ``fuzzy=True``, which reads 'sometime in March' as a date built
from today's day number.

**``get_value`` raises where its helper twin returns None, and that is deliberate.**
``cmdb_object_helpers.extract_field_value`` answers the same question tolerantly for callers reading
raw documents; the renderer relies on this one raising, because a summary field the object does not
carry has to fall back to a default rather than render an empty string. Neither is going away - see
the note on ``get_value``.

**Only the keys of ``CmdbObjectKey`` are stored.** The constructor used to accept ``**kwargs`` and
``setattr`` whatever else a document carried, so a drifted or misspelled key became a silent attribute
that ``to_json`` then dropped. Unknown keys are now ignored where they arrive - which is also what
lets the transient ``location_name`` of a create payload pass through without being stored
"""
from typing import Any
from datetime import datetime

from cmdb.utils import coerce_document_dates

from cmdb.class_schema.object_model.cmdb_object_schema import get_cmdb_object_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    OBJECT_DATE_KEYS,
)
from cmdb.models.type_model.field_type_enum import FieldType

from cmdb.errors.models.cmdb_object import (
    CmdbObjectInitError,
    CmdbObjectInitFromDataError,
    CmdbObjectToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbObject - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObject(CmdbDAO):
    """
    The CmdbObject is the basic data wrapper for storing and holding the pure objects within the CMDB

    Extends CmdbDAO
    """
    COLLECTION = 'framework.objects'
    DEFAULT_VERSION = '1.0.0'

    SCHEMA: dict[str, Any] = get_cmdb_object_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = CmdbObjectKey
    INIT_FROM_DATA_ERROR = CmdbObjectInitFromDataError
    TO_JSON_ERROR = CmdbObjectToJsonError

    # Normalised to real datetimes by normalize_document, and by GenericManager on a raw dict write
    DATE_FIELDS: tuple[str, ...] = tuple(date_key.value for date_key in OBJECT_DATE_KEYS)

    # The keys a stored document must carry to be readable, and only those: without a type or an owner
    # an object describes nothing, and both were already mandatory - the previous from_data read them
    # with data['key'] and int(), so a document missing one raised there instead.
    #
    # Everything else this list used to name (creation_time, active, version) is optional in the schema
    # and defaulted in normalize_document. Declaring them required while defaulting them anyway is what
    # let a document without a creation time be answered with 'now'; declaring MORE keys required would
    # make documents unreadable that this model has always read, on the collection where that costs the
    # most - the object list of a whole database
    REQUIRED_INIT_KEYS: list[str] = [
        CmdbObjectKey.TYPE_ID.value,
        CmdbObjectKey.AUTHOR_ID.value,
    ]

    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(CmdbObjectKey.TYPE_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': CmdbObjectKey.TYPE_ID.value,
            'unique': False,
        },
        {
            'keys': [(f'{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.VALUE.value}', CmdbDAO.DAO_ASCENDING)],
            'name': 'fields_value',
            'unique': False,
        },
        {
            'keys': [(
                f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.VALUES.value}'
                f'.{CmdbObjectMdsRowKey.DATA.value}.{CmdbObjectFieldKey.VALUE.value}',
                CmdbDAO.DAO_ASCENDING,
            )],
            'name': 'multi_data_sections_values_data_value',
            'unique': False,
        },
        # Compound (name, value) variants: both keys live in the same array element, so these are legal
        # compound multikey indexes. They serve the $elemMatch{name: X, value: Y} shape used throughout
        # (IPAM reference lookups, field-value queries) far more selectively than the value-only
        # indexes above, which stay for value-only queries
        {
            'keys': [
                (f'{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.NAME.value}', CmdbDAO.DAO_ASCENDING),
                (f'{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.VALUE.value}', CmdbDAO.DAO_ASCENDING),
            ],
            'name': 'fields_name_value',
            'unique': False,
        },
        {
            'keys': [
                (
                    f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.VALUES.value}'
                    f'.{CmdbObjectMdsRowKey.DATA.value}.{CmdbObjectFieldKey.NAME.value}',
                    CmdbDAO.DAO_ASCENDING,
                ),
                (
                    f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.VALUES.value}'
                    f'.{CmdbObjectMdsRowKey.DATA.value}.{CmdbObjectFieldKey.VALUE.value}',
                    CmdbDAO.DAO_ASCENDING,
                ),
            ],
            'name': 'multi_data_sections_values_data_name_value',
            'unique': False,
        },
    ]

    #pylint: disable=R0913
    def __init__(
        self,
        *,
        public_id: int,
        type_id: int,
        author_id: int,
        fields: list[dict[str, Any]],
        active: bool = True,
        version: str = DEFAULT_VERSION,
        creation_time: datetime | None = None,
        last_edit_time: datetime | None = None,
        editor_id: int | None = None,
        special_type: str | None = None,
        ci_explorer_tooltip: str | None = None,
        multi_data_sections: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        Initialises a CmdbObject

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the CmdbObject
            type_id (int): public_id of the CmdbType this object is an instance of
            author_id (int): public_id of the CmdbUser which created this CmdbObject
            fields (list): The object's field entries as name/value/type triples
            active (bool): Activation status (True = active, False = inactive). Defaults to True, the
                           same default the schema declares
            version (str): Current version of the CmdbObject. Defaults to DEFAULT_VERSION
            creation_time (datetime, optional): When the object was created. Stamped by the create
                                                route; never invented here, so a document that does not
                                                carry one reports None
            last_edit_time (datetime, optional): When the object was last edited, or None while it
                                                 never has been
            editor_id (int, optional): public_id of the CmdbUser which edited it last
            special_type (str, optional): The SpecialType member of the object's CmdbType, as the plain
                                          string it is stored as
            ci_explorer_tooltip (str, optional): Tooltip shown for this object in the CI Explorer
            multi_data_sections (list, optional): The MDS sections and their rows. None becomes []

        Raises:
            CmdbObjectInitError: If the initialisation failed
        """
        try:
            self.type_id: int = int(type_id)
            self.author_id: int = int(author_id)
            self.fields: list[dict[str, Any]] = fields
            self.active: bool = active
            self.version: str = version
            self.creation_time: datetime | None = creation_time
            self.last_edit_time: datetime | None = last_edit_time
            self.editor_id: int | None = editor_id
            self.special_type: str | None = special_type
            self.ci_explorer_tooltip: str | None = ci_explorer_tooltip
            self.multi_data_sections: list[dict[str, Any]] = multi_data_sections or []

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbObjectInitError(err) from err


    def __truediv__(self, other: "CmdbObject") -> dict[str, list[Any]]:
        """
        Compares the 'fields' of two CmdbObjects and returns which entries only one of them has

        Called when the '/' operator is used between two CmdbObjects. Entries are compared whole, so a
        field whose value changed appears in both lists - once as it was and once as it is.

        No caller uses it today; it is kept because it is public model API and its behaviour is now
        pinned by tests, so a future differ can rely on it

        Args:
            other (CmdbObject): The CmdbObject to compare with this one

        Raises:
            TypeError: If 'other' is not a CmdbObject

        Returns:
            dict: {'old': entries only this object has, 'new': entries only the other has}
        """
        if not isinstance(other, self.__class__):
            raise TypeError("Not the same class")

        return {
            'old': [entry for entry in self.fields if entry not in other.fields],
            'new': [entry for entry in other.fields if entry not in self.fields],
        }

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Normalises a raw document IN PLACE before the shared from_data reads it

        Turns both timestamps into real datetimes from any of the three shapes they arrive in - the
        ``{'$date': ...}`` wrapper the frontend sends, a timestamp string from an API client, or an
        already-normalised datetime - and applies the defaults the schema declares for the keys a
        document may omit (``fields``, ``multi_data_sections``, ``active``, ``version``).

        The defaults live here rather than on the signature because the shared ``from_data`` passes
        **every** key explicitly, so a document without ``active`` hands the constructor None and the
        signature default never runs. An explicit ``False`` is left alone - only a missing or null
        value is filled.

        A timestamp that is present but unreadable is refused rather than guessed

        Args:
            data (dict[str, Any]): The document or validated payload, edited in place

        Raises:
            ValueError: If a timestamp is present and cannot be read as a date
        """
        unusable_dates: list[str] = coerce_document_dates(data, cls.DATE_FIELDS)

        if unusable_dates:
            raise ValueError(f"Unreadable date value(s) for: {unusable_dates}")

        if data.get(CmdbObjectKey.FIELDS.value) is None:
            data[CmdbObjectKey.FIELDS.value] = []

        if data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) is None:
            data[CmdbObjectKey.MULTI_DATA_SECTIONS.value] = []

        if data.get(CmdbObjectKey.ACTIVE.value) is None:
            data[CmdbObjectKey.ACTIVE.value] = True

        if data.get(CmdbObjectKey.VERSION.value) is None:
            data[CmdbObjectKey.VERSION.value] = cls.DEFAULT_VERSION

# ---------------------------------------------------- ACCESSORS ----------------------------------------------------- #

    def get_type_id(self) -> int:
        """
        Returns the public_id of the CmdbType which is used as a blueprint for the CmdbObject

        Returns:
            int: public_id of the CmdbType of this CmdbObject
        """
        return self.type_id


    def get_all_fields(self) -> list[dict[str, Any]]:
        """
        Returns all top-level fields of the CmdbObject

        The MDS entries are NOT included: they live in multi_data_sections, one section and one row
        deep, and a caller wanting both walks them separately

        Returns:
            list: All top-level fields of the CmdbObject
        """
        return self.fields


    def get_value(self, field: str) -> Any:
        """
        Retrieves the value of a top-level field by its name

        **Raises for a field the object does not carry, deliberately.** The renderer depends on it: a
        summary field that a type declares but an older object never stored has to fall back to the
        type's default, and a None would render as an empty value instead. Callers reading raw
        documents who want the tolerant answer use ``cmdb_object_helpers.extract_field_value``, which
        returns None for exactly the same question

        Args:
            field (str): The name of the field whose value is to be retrieved

        Raises:
            ValueError: If the object carries no field of that name

        Returns:
            Any: The value of the field, which may itself be None
        """
        for entry in self.fields:
            if entry.get(CmdbObjectFieldKey.NAME.value) == field:
                return entry.get(CmdbObjectFieldKey.VALUE.value)

        raise ValueError(field)


    def has_fields_of_type(self, field_type: FieldType) -> bool:
        """
        Reports whether the object carries at least one field of the given FieldType

        Both places a field can live are searched - the top-level list and every row of every
        multi-data-section - because the guards that ask this question are about the object as a whole:
        whether it holds a location field (the location sync and its removal guard) and whether it
        holds a select field whose options may need propagating

        Args:
            field_type (FieldType): The field type to look for

        Returns:
            bool: True when at least one field entry declares that type
        """
        for field in self.fields or []:
            if field.get(CmdbObjectFieldKey.TYPE.value) == field_type:
                return True

        for section in self.multi_data_sections or []:
            for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
                for field in row.get(CmdbObjectMdsRowKey.DATA.value, []):
                    if field.get(CmdbObjectFieldKey.TYPE.value) == field_type:
                        return True

        return False
