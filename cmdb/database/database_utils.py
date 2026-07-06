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
List of useful functions for the database
"""
import re
import uuid
from logging import Logger, getLogger
import calendar
import time
import datetime
import random
from typing import Any
from collections.abc import Callable
from functools import wraps
from bson.dbref import DBRef
from bson.max_key import MaxKey
from bson.min_key import MinKey
from bson.objectid import ObjectId
from bson.timestamp import Timestamp
from bson.tz_util import utc

from pymongo.errors import PyMongoError, ServerSelectionTimeoutError, NetworkTimeout, ConnectionFailure

from cmdb.framework.search.search_result import SearchResult
from cmdb.framework.search.search_result_map import SearchResultMap

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

RE_TYPE = type(re.compile("re.Pattern"))

# -------------------------------------------------------------------------------------------------------------------- #

def object_hook(dct: dict[str, Any]) -> Any:
    """Helper function for converting json to mongo bson
    Args:
        dct: json data

    Returns:
        bson json format
    """
    if "$oid" in dct:
        return ObjectId(str(dct["$oid"]))

    if "$ref" in dct:
        return DBRef(dct["$ref"], dct["$id"], dct.get("$db", None))

    if "$date" in dct:
        try:
            # if timestamp
            return datetime.datetime.fromtimestamp(float(dct["$date"]) / 1000.0, utc)
        except ValueError:
            return datetime.datetime.fromisoformat(dct['$date'][:-1]).astimezone(utc)

    if "$regex" in dct:
        flags = 0
        if "i" in dct["$options"]:
            flags |= re.IGNORECASE
        if "m" in dct["$options"]:
            flags |= re.MULTILINE
        return re.compile(dct["$regex"], flags)

    if "$minKey" in dct:
        return MinKey()

    if "$maxKey" in dct:
        return MaxKey()

    if "$uuid" in dct:
        return uuid.UUID(dct["$uuid"])

    return dct

#pylint: disable=too-many-return-statements, too-many-branches
def default(obj: Any) -> Any:
    """Helper function for converting bson to json
    Args:
        obj: bson data

    Returns:
        json format
    """
    if isinstance(obj, (SearchResult,SearchResultMap)):
        return obj.to_json()

    if isinstance(obj, bytes):
        return obj.decode("utf-8")

    if isinstance(obj, ObjectId):
        return {"$oid": str(obj)}

    if isinstance(obj, DBRef):
        return obj.as_doc()

    if isinstance(obj, datetime.datetime):
        if obj.utcoffset() is not None:
            obj = obj - obj.utcoffset()

        millis = int(calendar.timegm(obj.timetuple()) * 1000 + obj.microsecond / 1000)
        return {"$date": millis}

    if isinstance(obj, RE_TYPE):
        flags = ""
        if obj.flags & re.IGNORECASE:
            flags += "i"
        if obj.flags & re.MULTILINE:
            flags += "m"
        return {
            "$regex": obj.pattern,
            "$options": flags
        }

    if isinstance(obj, MinKey):
        return {"$minKey": 1}

    if isinstance(obj, MaxKey):
        return {"$maxKey": 1}

    if isinstance(obj, dict):
        return obj

    if isinstance(obj, Timestamp):
        return {"t": obj.time, "i": obj.inc}

    if isinstance(obj, uuid.UUID):
        return {"$uuid": obj.hex}

    try:
        return obj.__dict__
    except Exception as err:
        raise TypeError(f"{obj} not JSON serializable - Type: {type(obj)}. Error: {err}") from err

# ---------------------------------------------- MONGODB RETRY DECORATOR --------------------------------------------- #

# Retry settings
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1  # in seconds

def retry_operation(func: Callable) -> Callable:
    """
    Decorator to retry database operations with exponential backoff on recoverable errors

    Retries on pymongo connection/timeout errors (up to MAX_RETRIES times, with jittered
    exponential backoff). Other errors are re-raised immediately.

    Args:
        func (Callable): The database operation (a method taking 'self' first) to wrap

    Returns:
        Callable: The wrapped operation with retry behavior
    """
    @wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        retries = 0
        retry_delay = INITIAL_RETRY_DELAY  # Initial delay in seconds

        while retries < MAX_RETRIES:
            try:
                return func(self, *args, **kwargs)
            except (PyMongoError, ServerSelectionTimeoutError, NetworkTimeout, ConnectionFailure) as e:
                # Handle MongoDB-specific exceptions
                retries += 1
                if retries < MAX_RETRIES:
                    # Exponential backoff with some random jitter
                    backoff_delay = retry_delay + random.uniform(0, 1)  # Add jitter to prevent thundering herd problem
                    LOGGER.warning(
                        "Attempt %d failed for %s: %s. Retrying in %.2fs...",
                        retries,
                        func.__name__,
                        e,
                        backoff_delay,
                    )
                    time.sleep(backoff_delay)
                    retry_delay *= 2  # Exponentially increase the delay
                else:
                    LOGGER.error("All %d attempts failed for %s: %s", MAX_RETRIES, func.__name__, e)
                    raise

        return None  # unreachable: the final retry attempt always returns or re-raises

    return wrapper
