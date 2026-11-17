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
The labeller summary lines are composed with: a person selector value as the text the reader sees

``objects_summary_helper`` composes the ``Type #id - a | b`` line in the manager layer, which reads no ACL; the caller
hands it this labeller, built from the reader's hidden Types. A value shows the labels of the persons and groups the
reader may READ (``selector_text.visible_labels_text``); none visible is the empty text, which the line leaves out
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.objects_summary_helper import PersonLabeller
from cmdb.framework.ipam.reference_disclosure import HiddenTypeIds
from cmdb.framework.person_selector.selector_render import resolve_person_selections
from cmdb.framework.person_selector.selector_text import visible_labels_text
from cmdb.framework.person_selector.selector_values import ids_of
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['person_labeller']


def person_labeller(objects_manager: ObjectsManager,
                    types_manager: TypesManager,
                    hidden_types: HiddenTypeIds) -> PersonLabeller:
    """
    The reader's labeller for summary lines

    Each call resolves the ids of all the values it is given in one pass (``resolve_person_selections``: two projected
    reads, none when no value holds an id)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        hidden_types (HiddenTypeIds): The reader's denied Types (``hidden_types_of``)

    Returns:
        PersonLabeller: values -> their visible label texts, in the same order
    """
    def label(values: list[Any]) -> list[str]:
        """
        The visible label texts of person selector values

        Args:
            values (list[Any]): Person selector values

        Raises:
            BaseManagerGetError: When a read fails

        Returns:
            list[str]: One text per value, empty when the reader sees none of its persons
        """
        object_ids: set[int] = {object_id for value in values for object_id in ids_of(value)}
        visible: dict[int, dict[str, Any]] = resolve_person_selections(
            objects_manager, types_manager, hidden_types, object_ids,
        )

        return [visible_labels_text(value, visible) for value in values]

    return label
