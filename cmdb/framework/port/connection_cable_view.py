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
The resolved ``cable`` block the connection READ routes return

A connection describes its cable in exactly one of two ways - the five ``cable_*`` values on its own
document, or a ``cable_ci_id`` naming the CABLE SpecialType CmdbObject that owns them. The write
routes refuse both at once, so the duplication can not exist in stored data; this module is the other
half of that decision: it turns either storage mode into ONE block, so a client renders a cabled link
without knowing which mode produced it.

Two normalisations happen here and nowhere else:

  - ``type`` is always a LABEL. An inline connection stores the CABLE_TYPE CmdbExtendableOption's
    public_id, a Cable CI stores the label its ordinary CmdbType select carries (a stored type field
    has no option_type key, which is why the two sides can not store the same thing - backlog #196).
    The inline id is resolved here, so a client never has to; ``type_id`` carries it alongside, and is
    null for a CI because there is no id to carry.
  - every value is text. The cable fields of a CmdbObject are ordinary field values and an import can
    leave a number in one, while the connection's own schema declares them strings.

Both reads are BATCHED over the whole page: one ``$in`` for the cable CIs and one for the option
labels, no matter how many connections are being rendered. A 48-port switch is two extra reads, not
ninety-six.

A cable CI that no longer exists is REPORTED, not repaired: the block keeps the id, carries
``resolved: false`` and holds no values. The reference is soft by design - deleting an inventoried
cable does not delete the link, because the two ports are still patched together.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.objects_manager import ObjectsManager

from cmdb.models.extendable_option_model import ExtendableOptionKey, OptionType
from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_connection_model.port_connection_constants import (
    CableSource,
    CableViewKey,
    ConnectionType,
    PortConnectionKey,
    CABLE_FIELD_KEYS,
    CABLE_VIEW_KEY,
)
from cmdb.models.special_type_model.cable_constants import CableField
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The Cable CI field that answers each key of the resolved block. TYPE_ID is absent on purpose: a
# CmdbType select stores its option's label and knows no CmdbExtendableOption id
CI_FIELD_BY_VIEW_KEY: dict[CableViewKey, CableField] = {
    CableViewKey.NAME: CableField.NAME,
    CableViewKey.TYPE: CableField.TYPE,
    CableViewKey.LENGTH: CableField.LENGTH,
    CableViewKey.COLOR: CableField.COLOR,
    CableViewKey.DESCRIPTION: CableField.DESCRIPTION,
}

# The connection field that answers each key of the resolved block for an INLINE cable. TYPE is
# absent: the stored value is an option id, and the label it resolves to is filled in separately
CONNECTION_FIELD_BY_VIEW_KEY: dict[CableViewKey, PortConnectionKey] = {
    CableViewKey.NAME: PortConnectionKey.CABLE_NAME,
    CableViewKey.LENGTH: PortConnectionKey.CABLE_LENGTH,
    CableViewKey.COLOR: PortConnectionKey.CABLE_COLOR,
    CableViewKey.DESCRIPTION: PortConnectionKey.CABLE_DESCRIPTION,
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    value reading                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def coerce_cable_text(value: Any) -> str | None:
    """
    Reads one cable value as the text the resolved block reports

    A Cable CI's fields are ordinary CmdbObject field values, so a CSV import can leave a number where
    the connection's own schema declares a string ('5' becoming 5). A scalar is rendered rather than
    refused - the read of a link must not fail over a value someone typed years ago - while a list or
    a dict is dropped, because there is no sensible one-line rendering of one and passing it through
    would put a shape into the block that no client expects

    Args:
        value (Any): The raw value read from the CI or from the connection

    Returns:
        str | None: The value as text, or None when it is absent, empty or not a scalar
    """
    if value is None:
        return None

    if isinstance(value, str):
        return value or None

    if isinstance(value, (int, float, bool)):
        return str(value)

    LOGGER.warning("[coerce_cable_text] Ignoring a cable value of unusable type: %s", type(value))

    return None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   batched lookups                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def collect_cable_ci_ids(connections: list[dict[str, Any]]) -> list[int]:
    """
    Collects the cable CI ids a page of connections references

    Args:
        connections (list[dict[str, Any]]): The stored connection documents

    Returns:
        list[int]: The referenced cable CI public_ids, each once
    """
    return list({
        connection[PortConnectionKey.CABLE_CI_ID.value]
        for connection in connections
        if isinstance(connection.get(PortConnectionKey.CABLE_CI_ID.value), int)
    })


def collect_cable_type_ids(connections: list[dict[str, Any]]) -> list[int]:
    """
    Collects the CABLE_TYPE option ids the INLINE connections of a page reference

    A connection naming a cable CI is skipped: its type comes from the CI as a label, so resolving an
    id it does not have would be a read for nothing

    Args:
        connections (list[dict[str, Any]]): The stored connection documents

    Returns:
        list[int]: The referenced CmdbExtendableOption public_ids, each once
    """
    return list({
        connection[PortConnectionKey.CABLE_TYPE.value]
        for connection in connections
        if connection.get(PortConnectionKey.CABLE_CI_ID.value) is None
        and isinstance(connection.get(PortConnectionKey.CABLE_TYPE.value), int)
    })


def load_cable_cis(objects_manager: ObjectsManager, cable_ci_ids: list[int]) -> dict[int, dict[str, Any]]:
    """
    Reads the referenced Cable CIs in one query

    The CmdbType is deliberately NOT re-checked here: the write routes refuse a cable_ci_id that does
    not name a CABLE SpecialType object, so a stored reference has already been judged, and a read of
    a link is not the place to re-litigate it

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        cable_ci_ids (list[int]): The referenced cable CI public_ids

    Returns:
        dict[int, dict[str, Any]]: The found CmdbObjects by public_id; ids that no longer exist are
            simply absent, which is what makes a dangling reference reportable
    """
    if not cable_ci_ids:
        return {}

    found: list[dict[str, Any]] = objects_manager.find_objects(
        criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': cable_ci_ids}},
        as_dict=True,
    )

    return {
        cable_ci[CmdbObjectKey.PUBLIC_ID.value]: cable_ci
        for cable_ci in found
        if CmdbObjectKey.PUBLIC_ID.value in cable_ci
    }


def load_cable_type_labels(
        extendable_options_manager: ExtendableOptionsManager,
        cable_type_ids: list[int]) -> dict[int, str]:
    """
    Reads the labels of the referenced CABLE_TYPE options in one query

    Scoped to the CABLE_TYPE list as well as to the ids: a connection's cable_type names an option of
    that list, and an id that belongs to another list is a stale reference rather than a label to show

    Args:
        extendable_options_manager (ExtendableOptionsManager): db interface for CmdbExtendableOptions
        cable_type_ids (list[int]): The referenced CmdbExtendableOption public_ids

    Returns:
        dict[int, str]: The option values by public_id; an id that resolves to nothing is absent
    """
    if not cable_type_ids:
        return {}

    found: list[dict[str, Any]] = extendable_options_manager.find(
        criteria={
            ExtendableOptionKey.PUBLIC_ID.value: {'$in': cable_type_ids},
            ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
        },
    )

    return {
        option[ExtendableOptionKey.PUBLIC_ID.value]: option[ExtendableOptionKey.VALUE.value]
        for option in found
        if isinstance(option.get(ExtendableOptionKey.VALUE.value), str)
    }

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     the block                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def build_cable_view(
        connection: dict[str, Any],
        cable_cis: dict[int, dict[str, Any]],
        cable_type_labels: dict[int, str]) -> dict[str, Any] | None:
    """
    Builds the resolved cable block of one connection

    An INTERNAL connection answers None rather than a block of nulls: a patch panel's front-to-rear
    pairing has no cable at all, and saying so once is clearer than five empty values a client has to
    interpret

    Args:
        connection (dict[str, Any]): The stored connection document
        cable_cis (dict[int, dict[str, Any]]): The Cable CIs of this page, by public_id
        cable_type_labels (dict[int, str]): The CABLE_TYPE option labels of this page, by public_id

    Returns:
        dict[str, Any] | None: The resolved cable block, or None for an INTERNAL connection
    """
    if connection.get(PortConnectionKey.CONNECTION_TYPE.value) == ConnectionType.INTERNAL:
        return None

    cable_ci_id: Any = connection.get(PortConnectionKey.CABLE_CI_ID.value)

    if cable_ci_id is None:
        return _build_inline_view(connection, cable_type_labels)

    return _build_ci_view(cable_ci_id, cable_cis.get(cable_ci_id))


def _build_inline_view(
        connection: dict[str, Any],
        cable_type_labels: dict[int, str]) -> dict[str, Any]:
    """
    Builds the block of a connection that carries its cable values itself

    Both type keys are filled: the stored id, and the label it resolves to. An id whose option was
    deleted keeps the id and reports no label - the same treatment a dangling cable CI gets, for the
    same reason

    Args:
        connection (dict[str, Any]): The stored connection document
        cable_type_labels (dict[int, str]): The CABLE_TYPE option labels of this page, by public_id

    Returns:
        dict[str, Any]: The resolved cable block, sourced INLINE
    """
    cable_type_id: Any = connection.get(PortConnectionKey.CABLE_TYPE.value)

    view: dict[str, Any] = {
        CableViewKey.SOURCE.value: CableSource.INLINE.value,
        CableViewKey.CABLE_CI_ID.value: None,
        CableViewKey.TYPE.value: cable_type_labels.get(cable_type_id),
        CableViewKey.TYPE_ID.value: cable_type_id,
    }

    for view_key, connection_key in CONNECTION_FIELD_BY_VIEW_KEY.items():
        view[view_key.value] = coerce_cable_text(connection.get(connection_key.value))

    return _in_view_order(view)


def _build_ci_view(cable_ci_id: int, cable_ci: dict[str, Any] | None) -> dict[str, Any]:
    """
    Builds the block of a connection whose cable is an inventoried CI

    ``type_id`` is always null here, and that is not a gap: the CI's cable type is an ordinary
    CmdbType select storing the option's LABEL, so there is no CmdbExtendableOption id to report.
    Resolving the label back to an id would guess across two lists that are allowed to drift apart
    (backlog #196)

    Args:
        cable_ci_id (int): public_id of the referenced Cable CI
        cable_ci (dict[str, Any] | None): The CI document, or None when it no longer exists

    Returns:
        dict[str, Any]: The resolved cable block, sourced from the CI
    """
    view: dict[str, Any] = {
        CableViewKey.SOURCE.value: CableSource.CI.value,
        CableViewKey.CABLE_CI_ID.value: cable_ci_id,
        CableViewKey.TYPE_ID.value: None,
    }

    if cable_ci is None:
        # Reported, never repaired and never cascaded: the link between the two ports is intact, only
        # the asset record describing its cable is gone
        LOGGER.warning(
            "[build_cable_view] Port connection references Cable CI %s, which does not exist", cable_ci_id,
        )
        view[CableViewKey.RESOLVED.value] = False

        for view_key in CI_FIELD_BY_VIEW_KEY:
            view[view_key.value] = None

        return _in_view_order(view)

    for view_key, ci_field in CI_FIELD_BY_VIEW_KEY.items():
        view[view_key.value] = coerce_cable_text(extract_field_value(cable_ci, ci_field.value))

    return _in_view_order(view)


def _in_view_order(view: dict[str, Any]) -> dict[str, Any]:
    """
    Orders a block's keys the way CableViewKey declares them

    Both branches fill the same keys in whatever order suits them, and a response whose fields move
    between two connections of the same list reads like two different shapes

    Args:
        view (dict[str, Any]): The block's values, in any order

    Returns:
        dict[str, Any]: The same values, keyed in CableViewKey order
    """
    return {key.value: view[key.value] for key in CableViewKey if key.value in view}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     attaching                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def attach_cable_views(
        connections: list[dict[str, Any]],
        objects_manager: ObjectsManager,
        extendable_options_manager: ExtendableOptionsManager) -> list[dict[str, Any]]:
    """
    Replaces the flat cable keys of every connection with the resolved cable block

    The flat keys are REMOVED rather than kept beside the block: returning a value twice, once raw and
    once resolved, leaves a client free to read the one that is null for half of the connections

    Two batched reads for the whole list, whatever its length - one for the Cable CIs and one for the
    CABLE_TYPE labels

    Args:
        connections (list[dict[str, Any]]): The stored connection documents
        objects_manager (ObjectsManager): db interface for CmdbObjects
        extendable_options_manager (ExtendableOptionsManager): db interface for CmdbExtendableOptions

    Returns:
        list[dict[str, Any]]: The connections, each carrying a 'cable' block instead of its cable keys
    """
    if not connections:
        return []

    cable_cis: dict[int, dict[str, Any]] = load_cable_cis(
        objects_manager, collect_cable_ci_ids(connections),
    )
    cable_type_labels: dict[int, str] = load_cable_type_labels(
        extendable_options_manager, collect_cable_type_ids(connections),
    )

    return [
        {
            **{
                key: value for key, value in connection.items()
                if key not in {cable_key.value for cable_key in CABLE_FIELD_KEYS}
            },
            CABLE_VIEW_KEY: build_cable_view(connection, cable_cis, cable_type_labels),
        }
        for connection in connections
    ]


def attach_cable_view(
        connection: dict[str, Any],
        objects_manager: ObjectsManager,
        extendable_options_manager: ExtendableOptionsManager) -> dict[str, Any]:
    """
    The single-connection form of attach_cable_views

    Args:
        connection (dict[str, Any]): The stored connection document
        objects_manager (ObjectsManager): db interface for CmdbObjects
        extendable_options_manager (ExtendableOptionsManager): db interface for CmdbExtendableOptions

    Returns:
        dict[str, Any]: The connection carrying a 'cable' block instead of its cable keys
    """
    return attach_cable_views([connection], objects_manager, extendable_options_manager)[0]
