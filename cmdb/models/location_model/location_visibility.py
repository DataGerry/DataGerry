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
Which CmdbLocation nodes a reader may see

A node carries its object's name and its Type's label and icon, so a node is exactly as visible as its object: a
reader whose group may not READ the node's Type does not see the node. And a hidden node hides its whole branch - a
readable node below it is not shown either, so the tree never presents a hierarchy that is not the real one (the
rule the CI Explorer follows by omitting a denied node). The synthetic root carries no Type and is never hidden
"""
from typing import Any, Collection, Iterable

from cmdb.models.location_model.location_constants import LocationKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['chain_is_hidden', 'node_is_hidden']


def node_is_hidden(node: dict[str, Any], denied_type_ids: Collection[int]) -> bool:
    """
    Answers whether one node's own Type is one the reader may not READ

    Args:
        node (dict[str, Any]): A stored or canonical CmdbLocation document
        denied_type_ids (Collection[int]): The Types the reader's group may not READ

    Returns:
        bool: True when the node's ``type_id`` is denied
    """
    return node.get(LocationKey.TYPE_ID.value) in denied_type_ids


def chain_is_hidden(chain: Iterable[dict[str, Any]], denied_type_ids: Collection[int]) -> bool:
    """
    Answers whether a node is hidden from the reader - itself or any node above it is of a denied Type

    Args:
        chain (Iterable[dict[str, Any]]): The node and its ancestors, in any order
        denied_type_ids (Collection[int]): The Types the reader's group may not READ

    Returns:
        bool: True when any node of the chain is hidden; False for an empty denial
    """
    if not denied_type_ids:
        return False

    return any(node_is_hidden(node, denied_type_ids) for node in chain)
