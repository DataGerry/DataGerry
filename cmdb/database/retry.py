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
The retry decorator of the database layer

``@retry_operation`` wraps the I/O methods of ``MongoConnector`` and ``MongoDatabaseManager``. Three
things decide what it does, and all three were wrong before 2026-09-09:

**1. WHICH failure is retried.** The decorated methods convert their exceptions into the typed
``cmdb.errors.database`` errors *inside* the method, so a decorator that only caught ``pymongo``
exceptions saw nothing: 34 of the 36 decorators in the layer were inert (discussion-backlog #142).
The policy therefore reads the *cause* of the typed error, and it has exactly two rules:

  * a **server-selection failure** is retried for any operation - the driver found no server, so the
    command never left the process and repeating it cannot repeat a write
  * any other **connection failure** is retried for **reads only** (``DocumentGetError``,
    ``DocumentAggregationError``, ``DatabaseConnectionError`` and the raw pymongo errors of the
    methods that do no writing). A dropped connection in the middle of a write may have been applied
    before the acknowledgement was lost, and this deployment has no retryable writes to fall back on
    (a standalone ``mongod`` is the norm on-premise)

Everything else - a duplicate key, a failed validation, a lock timeout, an operation failure - is a
deterministic answer and is raised immediately. Retrying one only spends the caller's time.

**2. HOW LONG it may take.** The old settings were 5 attempts with 1/2/4/8 s of backoff, i.e. up to
**19 seconds of `time.sleep` inside the request thread** - with gunicorn's sync workers, a burst of
failures blocks the pool. The budget is now sub-second (see the constants), and a retry is only
started when the whole call still fits inside ``RETRY_TIME_BUDGET``. That is what keeps the "server is
down" case from multiplying the driver's own 10 s server-selection timeout by the attempt count: the
first attempt already spends the budget, so the failure is reported instead of retried.

**3. WHETHER it is honest.** The wrapper logs which attempt failed and why, and the final failure is
raised unchanged - the caller's error type never depends on how many attempts it took
"""
import random
import time
from logging import Logger, getLogger
from typing import Any
from collections.abc import Callable
from functools import wraps

from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from cmdb.errors.database import (
    DatabaseConnectionError,
    DocumentAggregationError,
    DocumentGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RETRY_INITIAL_DELAY',
    'RETRY_JITTER',
    'RETRY_MAX_ATTEMPTS',
    'RETRY_TIME_BUDGET',
    'is_retryable',
    'retry_operation',
]

LOGGER: Logger = getLogger(__name__)

# How often an operation is attempted in total, including the first try
RETRY_MAX_ATTEMPTS: int = 3

# Delay before the second attempt, doubled for each further one: 0.2s, 0.4s
RETRY_INITIAL_DELAY: float = 0.2

# Added to each delay, so simultaneous callers do not retry in lockstep
RETRY_JITTER: float = 0.1

# Wall-clock budget for the whole call, the failed attempts included. A retry is skipped when it
# would not finish inside it - which is what bounds the "database unreachable" case, where a single
# attempt already costs the driver's serverSelectionTimeoutMS (10s, see MongoDatabaseManager)
RETRY_TIME_BUDGET: float = 5.0

# The driver never sent the command: retrying cannot duplicate a write
UNSENT_ERRORS: tuple[type[BaseException], ...] = (ServerSelectionTimeoutError,)

# The connection failed, possibly mid-command. ConnectionFailure covers AutoReconnect, NetworkTimeout
# and NotPrimaryError, so it is the whole family
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (ConnectionFailure,)

# The typed errors of operations that only read, so repeating one has no side effect
READ_ERRORS: tuple[type[BaseException], ...] = (
    DocumentGetError,
    DocumentAggregationError,
    DatabaseConnectionError,
)

# -------------------------------------------------------------------------------------------------------------------- #

def is_retryable(error: BaseException) -> bool:
    """
    Decides whether an operation that failed with this error may be attempted again

    The two rules of the module docstring, in order: a server-selection failure is always retryable,
    any other connection failure only for a read. The error's ``__cause__`` is consulted as well as
    the error itself, because the decorated methods wrap a pymongo failure into a typed
    ``cmdb.errors.database`` error before it reaches the decorator

    Args:
        error (BaseException): The error the attempt failed with

    Returns:
        bool: True when the operation may be retried
    """
    cause: BaseException | None = error.__cause__

    if isinstance(error, UNSENT_ERRORS) or isinstance(cause, UNSENT_ERRORS):
        return True

    if isinstance(error, TRANSIENT_ERRORS):
        # A raw pymongo failure that escaped a method which does not write (status, is_connected, …)
        return True

    if isinstance(cause, TRANSIENT_ERRORS):
        return isinstance(error, READ_ERRORS)

    return False


def retry_operation(func: Callable) -> Callable:
    """
    Retries a database operation while the failure is transient and the time budget allows it

    Args:
        func (Callable): The database operation (a method taking 'self' first) to wrap

    Returns:
        Callable: The wrapped operation
    """
    @wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        deadline: float = time.monotonic() + RETRY_TIME_BUDGET
        delay: float = RETRY_INITIAL_DELAY
        attempt: int = 0

        # Every path out of this loop is a return or a raise, so there is no unreachable tail
        while True:
            attempt += 1

            try:
                return func(self, *args, **kwargs)
            except Exception as err:
                if attempt >= RETRY_MAX_ATTEMPTS or not is_retryable(err):
                    raise

                backoff: float = delay + random.uniform(0, RETRY_JITTER)

                if time.monotonic() + backoff >= deadline:
                    LOGGER.warning(
                        "Attempt %d of %s failed (%s) and the %.1fs retry budget is spent - reporting it",
                        attempt, func.__name__, err, RETRY_TIME_BUDGET,
                    )

                    raise

                LOGGER.warning(
                    "Attempt %d/%d of %s failed (%s). Retrying in %.2fs...",
                    attempt, RETRY_MAX_ATTEMPTS, func.__name__, err, backoff,
                )

                time.sleep(backoff)
                delay *= 2

    return wrapper
