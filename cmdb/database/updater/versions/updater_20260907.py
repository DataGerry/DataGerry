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
Database update 20260907: stores the ISMS date fields as real dates instead of '$date' wrappers

An IsmsRiskAssessment carries four dates and an IsmsControlMeasureAssignment two. They reach the API
as the Mongo extended-JSON wrapper ``{'$date': <epoch millis>}`` - the shape every DataGerry response
uses for a datetime, and therefore the shape the frontend sends back - and the ISMS write routes
stored that wrapper verbatim, because their Cerberus schemas typed the fields as a plain ``dict`` and
no ISMS route applied ``json_util.object_hook`` (the object, DocAPI, media and importer routes all
do). What ended up in MongoDB was therefore a sub-document where a date belongs.

A sub-document cannot be compared, sorted, range-filtered or formatted as a date, so the ISMS
reports could only ever *project* those fields, and a ``?sort=risk_assessment_date`` on the list
route ordered documents by a nested key instead of by time. The models now normalise the fields on
every write path, which fixes new documents; this migration converts the ones already stored.

**The conversion never loses data.** Only a field currently holding an object is touched, and the
value is written back through ``$convert`` with both ``onError`` and ``onNull`` pointing at the
original field - so an object that is not a ``$date`` wrapper, or a wrapper whose payload cannot be
read as a date, is left exactly as it was rather than being nulled.

**Nothing changes on the wire.** ``cmdb.database.json_codec.default`` serialises a datetime back
into ``{'$date': <epoch millis>}``, so a converted document reaches the frontend in the same shape it
had before.

Re-run safe: each pass selects by the field's current BSON type, so a converted field no longer
matches and a completed run finds nothing to do, while a run interrupted halfway resumes with the
fields it had not reached yet. The version is bumped only after every field of both collections is
done.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.utils import MONGO_DATE_KEY

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The collections to migrate and the fields to migrate in them, taken from the models themselves so
# that a model gaining or losing a date field cannot leave this migration behind
DATE_FIELDS_BY_COLLECTION: dict[str, tuple[str, ...]] = {
    IsmsRiskAssessment.COLLECTION: IsmsRiskAssessment.DATE_FIELDS,
    IsmsControlMeasureAssignment.COLLECTION: IsmsControlMeasureAssignment.DATE_FIELDS,
}

# BSON type alias of the wrapper sub-document a legacy date is stored as; used to select exactly the
# documents that still need converting
BSON_OBJECT_TYPE: str = 'object'


def build_wrapped_date_filter(field: str) -> dict[str, Any]:
    """
    Builds the filter selecting the documents whose date field is still a wrapper sub-document

    Selecting by BSON type rather than by the presence of the inner key is what makes the migration
    re-runnable: a field already converted to a date no longer matches

    Args:
        field (str): Name of the date field

    Returns:
        dict[str, Any]: The MongoDB filter for that field
    """
    return {field: {'$type': BSON_OBJECT_TYPE}}


def build_date_conversion_pipeline(field: str) -> list[dict[str, Any]]:
    """
    Builds the aggregation-pipeline update converting one wrapped date field into a real date

    Reads the wrapper's inner key with ``$getField`` - needed because the key starts with a '$' and
    cannot be written as a field path - and converts it with ``$convert``, which reads both an epoch
    number and a timestamp string. ``onError`` / ``onNull`` return the untouched original field, so a
    value that is not a readable wrapper stays as it is instead of becoming null

    Args:
        field (str): Name of the date field

    Returns:
        list[dict[str, Any]]: The pipeline to hand to a plain update
    """
    field_path: str = f'${field}'

    return [
        {
            '$set': {
                field: {
                    '$convert': {
                        'input': {
                            '$getField': {
                                'field': {'$literal': MONGO_DATE_KEY},
                                'input': field_path,
                            },
                        },
                        'to': 'date',
                        'onError': field_path,
                        'onNull': field_path,
                    },
                },
            },
        },
    ]


def convert_wrapped_dates(dbm: MongoDatabaseManager, db_name: str, collection: str, field: str) -> int:
    """
    Converts one collection's date field from the wrapper sub-document into a real date

    Args:
        dbm (MongoDatabaseManager): Database manager used for the update
        db_name (str): Name of the database owning the collection
        collection (str): Name of the collection to migrate
        field (str): Name of the date field to convert

    Returns:
        int: Number of documents whose field was rewritten
    """
    result = dbm.update_many(
        collection,
        db_name,
        build_wrapped_date_filter(field),
        build_date_conversion_pipeline(field),
        plain=True,
    )

    return result.modified_count


# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260907 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260907(BaseDatabaseUpdate):
    """
    Converts the stored ISMS date fields from '$date' wrapper sub-documents into real BSON dates
    """
    def creation_date(self) -> int:
        return 20260907


    def description(self) -> str:
        return ("Converts the IsmsRiskAssessment and IsmsControlMeasureAssignment date fields from "
                "'$date' wrapper sub-documents into real BSON dates, so they can be sorted and filtered")


    def start_update(self) -> None:
        """
        Converts every wrapped date of both ISMS collections, then bumps the updater version

        Raises:
            UpdaterException: If any of the conversions fails
        """
        try:
            for collection, date_fields in DATE_FIELDS_BY_COLLECTION.items():
                for field in date_fields:
                    converted: int = convert_wrapped_dates(self.dbm, self.db_name, collection, field)

                    if converted:
                        LOGGER.info(
                            "[updater_20260907] Converted %s '%s' value(s) in %s into real dates",
                            converted, field, collection,
                        )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
