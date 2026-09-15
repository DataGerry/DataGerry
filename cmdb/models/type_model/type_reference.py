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
Implementation of TypeReference in DataGerry

A TypeReference is **what a reference field shows**: the expansion `CmdbMultiRender` writes under a
`FieldType.REFERENCE` field's `reference` key, describing the object the field points at. It is not a
stored document - it has no collection and no schema, is built per rendered field and only ever
serialised outward (`TypeReferenceKey` names the seven keys it answers).

Two properties of that payload are frontend contract:

* **`object_id` 0 is the empty reference.** `TypeReference.empty()` builds it, and the Angular
  reference field hides the whole block while it sees 0 - which is why the renderer answers an empty
  reference rather than `None` for a field with no value, an unresolvable object, or a failure.
* **`line` wins over the parts when it is set.** The frontend shows the filled summary line if there
  is one, and falls back to icon + label + `#`id + the summary fields when it is empty. An empty line
  is therefore the graceful degrade, and that is what a line whose placeholders cannot be filled ends
  up as (see `fill_line` - the renderer clears it and reports).
"""
import re

from cmdb.models.type_model.type_reference_key_enum import TypeReferenceKey

from cmdb.errors.models.cmdb_type import CmdbTypeReferenceLineFillError
# -------------------------------------------------------------------------------------------------------------------- #

# Detects a `str.format` placeholder in a summary line. Compiled once: the check runs for every
# reference field of every rendered object, and the renderer caches types and objects for exactly
# that reason
SUMMARY_LINE_PLACEHOLDER_PATTERN: re.Pattern[str] = re.compile(r'{.*?}')

# The identity values of the EMPTY reference - a reference field the renderer could not resolve. The
# frontend tests OBJECT_ID against 0 to hide the block, so the two ids are not merely 'unset' here
EMPTY_REFERENCE_TYPE_ID: int = 0
EMPTY_REFERENCE_OBJECT_ID: int = 0

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     TypeReference                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeReference:
    """
    What a reference field shows: the resolved description of the object it points at
    """

    #pylint: disable=R0913, R0917
    def __init__(
            self,
            type_id: int,
            object_id: int,
            type_label: str | None = None,
            line: str | None = None,
            prefix: bool = False,
            icon: str | None = None,
            summaries: list | None = None,
        ) -> None:
        """
        Initialises a TypeReference

        The three optional payload values are normalised here rather than at serialisation time, so
        a reference answers the same types whether it was resolved or not: no null label, no null
        summary list, and a two-state prefix flag

        Args:
            type_id (int): public_id of the referenced object's CmdbType (0 on the empty reference)
            object_id (int): public_id of the referenced CmdbObject (0 marks the empty reference)
            type_label (str | None): Label of that CmdbType. None becomes an empty label
            line (str | None): The type's summary line for the referenced object, placeholders still
                               unfilled. None and '' both mean "no line", which is what makes the
                               frontend show the label / id / summaries instead
            prefix (bool): Whether the summary configuration asks for a prefixed label
            icon (str | None): Icon class of that CmdbType
            summaries (list | None): The referenced object's summary fields. None becomes an empty list
        """
        self.type_id: int = type_id
        self.object_id: int = object_id
        self.type_label: str = type_label or ''
        self.summaries: list = summaries or []
        self.line: str | None = line
        self.icon: str | None = icon
        self.prefix: bool = bool(prefix)

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def empty(cls) -> "TypeReference":
        """
        Builds the EMPTY reference, the answer for a reference that could not be resolved

        A reference field always carries a `reference` dict - the frontend and the exporter both read
        into it - so an unresolved field answers this instead of None, and is recognised by its
        `object_id` of 0. Built here rather than at each of the renderer's early returns, because the
        sentinel is part of the payload contract

        Returns:
            TypeReference: A reference whose ids are 0 and whose label and line are empty
        """
        return cls(
            type_id=EMPTY_REFERENCE_TYPE_ID,
            object_id=EMPTY_REFERENCE_OBJECT_ID,
            type_label='',
            line='',
        )


    @classmethod
    def to_json(cls, instance: "TypeReference") -> dict[str, str | int | bool | list | None]:
        """
        Returns a TypeReference as JSON representation

        The keys are `TypeReferenceKey`, which is the payload contract three consumers read - see the
        module docstring

        Args:
            instance (TypeReference): TypeReference which should be transformed

        Returns:
            dict: JSON representation of the given TypeReference
        """
        return {
            TypeReferenceKey.TYPE_ID.value: instance.type_id,
            TypeReferenceKey.OBJECT_ID.value: instance.object_id,
            TypeReferenceKey.LINE.value: instance.line,
            TypeReferenceKey.TYPE_LABEL.value: instance.type_label,
            TypeReferenceKey.SUMMARIES.value: instance.summaries,
            TypeReferenceKey.ICON.value: instance.icon,
            TypeReferenceKey.PREFIX.value: instance.prefix,
        }

# ------------------------------------------------- GENERAL FUNCTIONS ------------------------------------------------ #

    def line_requires_fields(self) -> bool:
        """
        Reports whether the summary line carries `str.format` placeholders to fill

        A line without them is shown as it is, which is what makes the summary FIELDS redundant for
        such a reference. A line that is absent, empty or not text at all requires nothing - answered
        here rather than raising, so a caller does not have to guard the call (`self.line` is
        optional by construction, and a drifted type can put a non-string there)

        Examples:
            `example {}` -> True
            `example` -> False

        Returns:
            bool: True if the line contains at least one placeholder, otherwise False
        """
        if not isinstance(self.line, str):
            return False

        return SUMMARY_LINE_PLACEHOLDER_PATTERN.search(self.line) is not None


    def fill_line(self, inputs: list) -> None:
        """
        Fills the summary line's placeholders with the referenced object's summary values

        Args:
            inputs (list): The summary values, in the order the line's placeholders expect them

        Raises:
            CmdbTypeReferenceLineFillError: If the line and the values do not fit - too few values
                for its placeholders, or a stray brace. The line is left UNFILLED in that case, so a
                caller that answers it anyway would show the raw template; the renderer clears it
                instead and reports
        """
        try:
            self.line = self.line.format(*inputs)
        except Exception as err:
            raise CmdbTypeReferenceLineFillError(
                f"Type reference summary line do not fit with inputs: {self.line}!"
            ) from err
