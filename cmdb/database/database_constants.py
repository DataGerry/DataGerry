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

# Minimal Update Version since Cloud-Version
MIN_CLOUD_UPDATER_VERSION = 20240603

# Retry up to x times if duplicate key occurs while creating a document in the database
MAX_DUPLICATE_KEY_RETRIES = 10

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
