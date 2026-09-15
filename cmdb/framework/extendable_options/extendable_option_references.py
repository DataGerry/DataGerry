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
Which collections reference a CmdbExtendableOption, and the two operations that need to know

A CmdbExtendableOption is referenced by public_id from other documents, so 'is this option still in
use' and 're-point these references at another option' both need the same map of
OptionType -> (collection, field). Two callers consume it and neither can own it:

    extendable_options_helper.is_extendable_option_used   the pre-delete guard in the REST layer
    updater_20260902                                      the de-duplication pass, which re-points
                                                          a discarded duplicate's references before
                                                          deleting it

The map lives in the framework layer because it names the ISMS and object-group collections, and a
module inside ``cmdb/models/extendable_option_model`` that imported those model classes would close
an import cycle (``CmdbObjectGroup`` imports this feature's OptionType).

Both operations take a MongoDatabaseManager and a database name rather than managers, because an
updater has no request user and therefore no ManagerProvider.
"""
from logging import Logger, getLogger
from typing import Any, NamedTuple

from cmdb.database.mongo_database_manager import MongoDatabaseManager

from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.object_group_model.cmdb_object_group import CmdbObjectGroup
from cmdb.models.port_model.cmdb_port import CmdbPort
from cmdb.models.port_model.port_constants import PORT_SELECT_FIELD_OPTION_TYPES
from cmdb.models.port_connection_model.cmdb_port_connection import CmdbPortConnection
from cmdb.models.port_connection_model.port_connection_constants import PortConnectionKey
from cmdb.models.isms_model.isms_threat import IsmsThreat
from cmdb.models.isms_model.isms_vulnerability import IsmsVulnerability
from cmdb.models.isms_model.isms_risk import IsmsRisk
from cmdb.models.isms_model.isms_control_measure import IsmsControlMeasure
from cmdb.models.isms_model.isms_risk_assessment import IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment import IsmsControlMeasureAssignment

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# An existence check only needs to know whether there is at least one match, so the server may stop
# counting at the first one
EXISTENCE_CHECK_LIMIT: int = 1


class ExtendableOptionUsageField(BaseStrEnum):
    """Field names on the referencing collections that hold a CmdbExtendableOption public_id"""
    SOURCE = 'source'                                # threats / vulnerabilities / control measures
    CATEGORIES = 'categories'                        # object groups
    IMPLEMENTATION_STATE = 'implementation_state'    # control measures
    IMPLEMENTATION_STATUS = 'implementation_status'  # risk assessments / control-measure assignments
    CATEGORY_ID = 'category_id'                      # risks


class ExtendableOptionReference(NamedTuple):
    """
    One place a CmdbExtendableOption public_id can be stored

    Attributes:
        collection (str): Name of the referencing collection
        field (str): Name of the field holding the referenced public_id
        is_array (bool): True when the field is a list of public_ids rather than a single one, which
            changes how a reference is re-pointed ($addToSet + $pull instead of $set)
    """
    collection: str
    field: str
    is_array: bool = False


# Every reference to a CmdbExtendableOption in the database, keyed by the OptionType being pointed at
EXTENDABLE_OPTION_REFERENCES: dict[OptionType, tuple[ExtendableOptionReference, ...]] = {
    OptionType.THREAT_VULNERABILITY: (
        ExtendableOptionReference(IsmsThreat.COLLECTION, ExtendableOptionUsageField.SOURCE.value),
        ExtendableOptionReference(IsmsVulnerability.COLLECTION, ExtendableOptionUsageField.SOURCE.value),
    ),
    OptionType.OBJECT_GROUP: (
        ExtendableOptionReference(
            CmdbObjectGroup.COLLECTION,
            ExtendableOptionUsageField.CATEGORIES.value,
            is_array=True,
        ),
    ),
    OptionType.CONTROL_MEASURE: (
        ExtendableOptionReference(IsmsControlMeasure.COLLECTION, ExtendableOptionUsageField.SOURCE.value),
    ),
    OptionType.IMPLEMENTATION_STATE: (
        ExtendableOptionReference(
            IsmsControlMeasure.COLLECTION,
            ExtendableOptionUsageField.IMPLEMENTATION_STATE.value,
        ),
        ExtendableOptionReference(
            IsmsRiskAssessment.COLLECTION,
            ExtendableOptionUsageField.IMPLEMENTATION_STATUS.value,
        ),
        ExtendableOptionReference(
            IsmsControlMeasureAssignment.COLLECTION,
            ExtendableOptionUsageField.IMPLEMENTATION_STATUS.value,
        ),
    ),
    OptionType.RISK: (
        ExtendableOptionReference(IsmsRisk.COLLECTION, ExtendableOptionUsageField.CATEGORY_ID.value),
    ),
    # The three port select fields, DERIVED from the port model's own field -> OptionType map rather
    # than restated here, so a port field and its reference entry cannot drift apart. Each field name
    # doubles as its own usage-field name, which is why PortKey and not ExtendableOptionUsageField
    # names them
    **{
        option_type: (ExtendableOptionReference(CmdbPort.COLLECTION, field.value),)
        for field, option_type in PORT_SELECT_FIELD_OPTION_TYPES.items()
    },
    # A connection's cable type. Only the CONNECTION is listed: the Cable CI's own cable-type field is
    # an ordinary CmdbType select carrying a snapshot of the values as inline options, so it holds no
    # option public_id and deleting an option can not dangle a reference there
    OptionType.CABLE_TYPE: (
        ExtendableOptionReference(CmdbPortConnection.COLLECTION, PortConnectionKey.CABLE_TYPE.value),
    ),
}

# -------------------------------------------------------------------------------------------------------------------- #

def get_option_references(option_type: Any) -> tuple[ExtendableOptionReference, ...]:
    """
    Returns every place a CmdbExtendableOption of the given OptionType can be referenced from

    Args:
        option_type (Any): The OptionType to look up. Accepts the plain stored string as well, since
            a document read back from MongoDB carries the value and not the enum member

    Returns:
        tuple[ExtendableOptionReference, ...]: The references, empty when the OptionType is unknown
            or nothing references it (yet)
    """
    return EXTENDABLE_OPTION_REFERENCES.get(option_type, ())


def is_option_referenced(
        dbm: MongoDatabaseManager,
        db_name: str,
        option_type: Any,
        public_id: int) -> bool:
    """
    Checks whether any document still references the given CmdbExtendableOption

    Stops at the first referencing collection that matches, and counts with a limit of one, so the
    server can short-circuit instead of counting every match

    Args:
        dbm (MongoDatabaseManager): Database manager used for the counts
        db_name (str): Name of the database to check in
        option_type (Any): OptionType of the option, deciding which collections are consulted
        public_id (int): public_id of the CmdbExtendableOption

    Returns:
        bool: True if at least one document references the option, False otherwise (including when
            nothing can reference this OptionType)
    """
    for reference in get_option_references(option_type):
        count: int = dbm.count(
            reference.collection,
            db_name,
            {reference.field: public_id},
            limit=EXISTENCE_CHECK_LIMIT,
        )

        if count > 0:
            return True

    return False


def repoint_option_references(
        dbm: MongoDatabaseManager,
        db_name: str,
        option_type: Any,
        from_id: int,
        to_id: int) -> int:
    """
    Moves every reference to one CmdbExtendableOption onto another one

    Used before a duplicate option is deleted, so the documents that pointed at it keep pointing at
    an option with the same value instead of at nothing.

    Re-run safe in both shapes. A scalar field is simply set to the keeper, which no longer matches
    the filter afterwards. An array field is handled in two statements, keeper first: $addToSet adds
    the keeper (a no-op when it is already there, which is what makes a repeated run harmless), and
    only then is the discarded id pulled - so an interruption between the two leaves both ids in the
    array rather than losing the reference, and the next run finishes the job

    Args:
        dbm (MongoDatabaseManager): Database manager performing the updates
        db_name (str): Name of the database to update
        option_type (Any): OptionType of the two options, deciding which collections are rewritten
        from_id (int): public_id of the option being discarded
        to_id (int): public_id of the option being kept

    Returns:
        int: How many documents were modified
    """
    modified: int = 0

    for reference in get_option_references(option_type):
        criteria: dict[str, Any] = {reference.field: from_id}

        if reference.is_array:
            dbm.update_many(
                reference.collection,
                db_name,
                criteria,
                {reference.field: to_id},
                add_to_set=True,
            )
            result = dbm.update_many_pull(reference.collection, db_name, criteria, {reference.field: from_id})
        else:
            result = dbm.update_many(reference.collection, db_name, criteria, {reference.field: to_id})

        if result.modified_count:
            LOGGER.info(
                "[repoint_option_references] %s.%s: %s document(s) moved from option ID:%s to ID:%s",
                reference.collection, reference.field, result.modified_count, from_id, to_id,
            )

        modified += result.modified_count

    return modified
