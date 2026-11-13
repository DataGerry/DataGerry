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
Database update 20261117: stores the ISMS dates still held as a calendar-date object as real dates

The frontend's date picker sends a date as ``{'year': 2026, 'month': 11, 'day': 27}``. While the ISMS schemas typed
the date fields as a plain object, that object was stored as it was; ``updater_20260907`` converted only the
``{'$date': ...}`` wrappers and left these alone. The models read them since (``coerce_calendar_date``), but MongoDB
cannot sort or range-filter a sub-document, so this update converts them into the date the model reads: midnight UTC
of that day.

**Exactly the objects the model reads are converted.** The filter selects an object of exactly the three keys, each a
whole number (BSON int or long) within the calendar's ranges; the pipeline builds the date and keeps it only when it
names the same day back - February 30th would roll over to March 2nd, so such an object is left as it is, like every
other object the model would refuse.

Re-run safe: a converted field is a date and no longer matches; an object left as it was is rewritten with itself,
which modifies nothing. The version is bumped only after every field of both collections is done
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
DATE_FIELDS_BY_COLLECTION: dict[str, tuple[str, ...]] = {
    'isms.riskAssessment': ('risk_assessment_date', 'planned_implementation_date', 'finished_implementation_date',
                            'audit_done_date'),
    'isms.controlMeasureAssignment': ('planned_implementation_date', 'finished_implementation_date'),
}

# Each part of the calendar-date object with the range it must lie in
CALENDAR_PART_RANGES: dict[str, tuple[int, int]] = {'year': (1, 9999), 'month': (1, 12), 'day': (1, 31)}

WHOLE_NUMBER_TYPES: list[str] = ['int', 'long']
BSON_OBJECT_TYPE: str = 'object'
TIMEZONE_UTC: str = 'UTC'
BUILT_DATE_VARIABLE: str = 'built'


def build_calendar_date_filter(field: str) -> dict[str, Any]:
    """
    Builds the filter selecting the documents whose date field is a calendar-date object

    Args:
        field (str): Name of the date field

    Returns:
        dict[str, Any]: The MongoDB filter: an object of exactly the three parts, each a whole number in its range
    """
    field_path: str = f'${field}'
    criteria: dict[str, Any] = {field: {'$type': BSON_OBJECT_TYPE}}

    for part, (lowest, highest) in CALENDAR_PART_RANGES.items():
        criteria[f'{field}.{part}'] = {'$type': WHOLE_NUMBER_TYPES, '$gte': lowest, '$lte': highest}

    # $cond, not $and: $objectToArray fails on a non-object, and only $cond is guaranteed not to evaluate it then
    criteria['$expr'] = {
        '$cond': {
            'if': {'$eq': [{'$type': field_path}, BSON_OBJECT_TYPE]},
            'then': {'$eq': [{'$size': {'$objectToArray': field_path}}, len(CALENDAR_PART_RANGES)]},
            'else': False,
        },
    }

    return criteria


def build_calendar_date_pipeline(field: str) -> list[dict[str, Any]]:
    """
    Builds the aggregation-pipeline update turning a calendar-date object into midnight UTC of that day

    ``$dateFromParts`` rolls an impossible day over into the next month, so the built date is kept only when its
    month and day read back as sent; else the field keeps its object

    Args:
        field (str): Name of the date field

    Returns:
        list[dict[str, Any]]: The pipeline to hand to a plain update
    """
    field_path: str = f'${field}'
    built: str = f'$${BUILT_DATE_VARIABLE}'

    return [
        {
            '$set': {
                field: {
                    '$let': {
                        'vars': {
                            BUILT_DATE_VARIABLE: {
                                '$dateFromParts': {
                                    'year': f'{field_path}.year',
                                    'month': f'{field_path}.month',
                                    'day': f'{field_path}.day',
                                    'timezone': TIMEZONE_UTC,
                                },
                            },
                        },
                        'in': {
                            '$cond': {
                                'if': {
                                    '$and': [
                                        {'$eq': [{'$month': {'date': built, 'timezone': TIMEZONE_UTC}},
                                                 f'{field_path}.month']},
                                        {'$eq': [{'$dayOfMonth': {'date': built, 'timezone': TIMEZONE_UTC}},
                                                 f'{field_path}.day']},
                                    ],
                                },
                                'then': built,
                                'else': field_path,
                            },
                        },
                    },
                },
            },
        },
    ]


def convert_calendar_dates(dbm: MongoDatabaseManager, db_name: str, collection: str, field: str) -> int:
    """
    Converts one collection's date field from the calendar-date object into a real date

    Args:
        dbm (MongoDatabaseManager): Database manager used for the update
        db_name (str): Name of the database owning the collection
        collection (str): Name of the collection to migrate
        field (str): Name of the date field to convert

    Returns:
        int: Number of documents whose field was rewritten
    """
    result = dbm.update_many_raw(collection, db_name, build_calendar_date_filter(field),
                                 build_calendar_date_pipeline(field))

    return result.modified_count

# ---------------------------------------------- Update20261117 - CLASS ---------------------------------------------- #

class Update20261117(BaseDatabaseUpdate):
    """
    Converts the ISMS date fields still stored as a calendar-date object into real BSON dates

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261117


    def description(self) -> str:
        return ("Converts the IsmsRiskAssessment and IsmsControlMeasureAssignment dates stored as a "
                "{year, month, day} object into real BSON dates")


    def start_update(self) -> None:
        """
        Converts every calendar-date object of both ISMS collections, then bumps the version

        Raises:
            UpdaterException: If a conversion or the version write fails
        """
        try:
            for collection, date_fields in DATE_FIELDS_BY_COLLECTION.items():
                for field in date_fields:
                    converted: int = convert_calendar_dates(self.dbm, self.db_name, collection, field)

                    if converted:
                        LOGGER.info("[updater_20261117] Converted %s '%s' value(s) in %s into real dates",
                                    converted, field, collection)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
