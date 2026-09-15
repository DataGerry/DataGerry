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
This module provides all constants for the Database section
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Collection storing the public_id counters
PUBLIC_ID_COUNTER_COLLECTION = "datastorage.counter"

# Schema baseline assumed for a database that carries no 'updater' settings document yet: it is
# seeded with this version, so every registered migration at or below it never runs. It is therefore
# the oldest schema DataGerry can migrate FROM - the migrations up to and including this version were
# removed on 2026-07-30, so a database below it cannot be brought forward any more. Applies in every
# mode (it predates cloud mode but is not cloud-specific)
BASELINE_UPDATER_VERSION = 20240603

# Retry up to x times if duplicate key occurs while creating a document in the database
MAX_DUPLICATE_KEY_RETRIES = 10

# The document field the retry loop above is about. A duplicate-key error is only worth retrying when
# it is THIS index that was violated - a fresh public_id cannot resolve any other unique constraint
PUBLIC_ID_FIELD: str = "public_id"

# Keys of a pymongo DuplicateKeyError's 'details' dict, used to tell which unique index was violated:
# 'keyPattern' names the indexed fields, 'keyValue' the values that collided. Both are reported by
# MongoDB 4.2 and newer; a synthesised error may carry neither
MONGO_ERROR_KEY_PATTERN: str = "keyPattern"
MONGO_ERROR_KEY_VALUE: str = "keyValue"

# Name of the database handling caches
DG_CACHE_DB = "dg_caches"

# Maximum number of operations sent per bulk_write batch
BULK_WRITE_BATCH_SIZE: int = 500

# Interval (in seconds) between background keep-alive pings to MongoDB
KEEPALIVE_PING_INTERVAL_SECONDS: int = 50

# MongoDB error code reported on a lock timeout (OperationFailure.code)
MONGO_LOCK_TIMEOUT_ERROR_CODE: int = 24

# MongoDB descending sort direction (mirrors pymongo.DESCENDING)
MONGO_SORT_DESCENDING: int = -1

# Environment variable holding a full MongoDB connection string. When set it replaces the
# host/port pair AND decides whether the connector requests TLS - see MongoConnector.__init__
MONGO_CONNECTION_STRING_ENV: str = "CONNECTION_STRING"

# Connection-string scheme that makes the connector request TLS. Any other scheme (including a
# plain "mongodb://" string that already asks for TLS itself) does not - see discussion-backlog #139
MONGO_SRV_SCHEME_PREFIX: str = "mongodb+srv://"

# MongoClient option names the connector normalises: the deprecated 'ssl' flag is dropped in favour
# of 'tls', which the connector sets itself unless the caller already provided it
MONGO_SSL_OPTION: str = "ssl"
MONGO_TLS_OPTION: str = "tls"

# Command used to probe whether the server answers, and the key of its acknowledgement flag
MONGO_HELLO_COMMAND: str = "hello"
MONGO_COMMAND_OK_KEY: str = "ok"
MONGO_COMMAND_OK_VALUE: int = 1
