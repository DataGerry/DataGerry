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
Person selections as text, and selector values cut to what a reader may see - pure, no reads

Wherever a selection is shown as text rather than as ``persons`` entries - a summary, a reference's line, the CI
Explorer, a human-readable export - it is the visible selections' labels joined by ``SELECTOR_LABEL_SEPARATOR``; a
selection without a label shows its id. ``visible`` is always ``selector_render.resolve_person_selections``' answer:
only the ids the reader may READ are in it
"""
from typing import Any, Mapping

from cmdb.framework.person_selector.person_selector_constants import PersonSelectionKey, SELECTOR_LABEL_SEPARATOR
from cmdb.framework.person_selector.selector_values import ids_of
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['kept_value', 'visible_selections', 'selection_labels_text', 'visible_labels_text']


def kept_value(value: Any, multiple: bool, visible: Mapping[int, dict[str, Any]]) -> Any:
    """
    A selector value with every id the reader may not see taken out, in the selector's shape

    Args:
        value (Any): The stored value - one id, a list of ids, or nothing
        multiple (bool): Whether the selector holds several
        visible (Mapping[int, dict[str, Any]]): The selections the reader may see, by id

    Returns:
        Any: The kept ids as a list for a selector holding several, else the first kept id or None
    """
    kept: list[int] = [object_id for object_id in ids_of(value) if object_id in visible]

    if multiple:
        return kept

    return kept[0] if kept else None


def visible_selections(value: Any, visible: Mapping[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The rendered selections of the ids a value holds that the reader may see, in the value's order

    Args:
        value (Any): A selector value - one id, a list of ids, or nothing
        visible (Mapping[int, dict[str, Any]]): The selections the reader may see, by id

    Returns:
        list[dict[str, Any]]: One selection per visible id
    """
    return [visible[object_id] for object_id in ids_of(value) if object_id in visible]


def selection_labels_text(selections: list[dict[str, Any]]) -> str:
    """
    The labels of rendered selections as one text - a selection without a label shows its id

    Args:
        selections (list[dict[str, Any]]): Rendered selections (``PersonSelectionKey``)

    Returns:
        str: The joined labels, empty for no selection
    """
    return SELECTOR_LABEL_SEPARATOR.join(
        str(selection.get(PersonSelectionKey.LABEL.value) or selection.get(PersonSelectionKey.OBJECT_ID.value))
        for selection in selections
    )


def visible_labels_text(value: Any, visible: Mapping[int, dict[str, Any]]) -> str:
    """
    A selector value as the text a reader sees: the labels of the visible selections it holds

    Args:
        value (Any): A selector value - one id, a list of ids, or nothing
        visible (Mapping[int, dict[str, Any]]): The selections the reader may see, by id

    Returns:
        str: The joined labels, empty when the reader sees none of them
    """
    return selection_labels_text(visible_selections(value, visible))
