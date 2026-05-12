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
Logging configuration for the DataGerry process tree

Centralises log-level resolution (driven by `cmdb.__MODE__` with a per-call minimum floor) and
produces the `logging.config.dictConfig` payload consumed at process startup. The payload wires
three rotating-file targets — one per-process daemon log named after the active
`multiprocessing` process so each `ProcessController` child writes its own file, plus separate
gunicorn access / error logs — and routes the `__main__` and `cmdb` loggers to both the console
and the daemon log
"""
from typing import Any
import os
import multiprocessing
import pathlib

import cmdb
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_LOG_DIR: str = os.path.join(os.path.dirname(__file__), '../../logs/')

LOGLEVELS: dict[str, int] = {
    "NOTSET": 0,
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50
}


def get_log_level(minlevel: str | None = None) -> str:
    """
    Resolves the effective log-level name to assign to a logger

    Starts from WARNING and lets `cmdb.__MODE__` override it when its value is one of the known
    level names (NOTSET / DEBUG / INFO / WARNING / ERROR / CRITICAL) — this is how the `--debug`
    CLI flag reaches the logging layer. `minlevel` is then applied as a verbosity floor: when
    set and more verbose than the resolved level it wins, so callers that need at least INFO
    output (see the `__main__` logger in `get_logging_conf`) cannot be silenced by a
    higher-level mode

    Args:
        minlevel (str | None): Optional verbosity floor expressed as a level name; values
            outside `LOGLEVELS` are ignored

    Returns:
        str: Level name suitable for the `level` field of a `dictConfig` logger entry
    """
    loglevel = "WARNING"

    if cmdb.__MODE__ in LOGLEVELS:
        loglevel = cmdb.__MODE__

    if minlevel and minlevel in LOGLEVELS:
        if LOGLEVELS.get(minlevel) < LOGLEVELS.get(loglevel):
            loglevel = minlevel

    return loglevel


def get_logging_conf() -> dict[str, Any]:
    """
    Builds the `logging.config.dictConfig` payload for the current process

    Ensures `DEFAULT_LOG_DIR` exists and embeds the active `multiprocessing` process name into
    the daemon log filename so each spawned `CmdbProcess` writes to its own rotating file
    (`<proc_name>.log`, 10 MB × 4 backups). The `__main__` and `cmdb` loggers fan out to both
    the console and the daemon log; `gunicorn.access` and `gunicorn.error` go to dedicated
    rotating files. Effective levels for the `__main__` and `cmdb` loggers come from
    `get_log_level`, with `__main__` floored at INFO so startup messages are never suppressed

    Note: `disable_existing_loggers` is True, so any logger created before this config is
    applied is disabled. Callers must apply it before module-level `getLogger(__name__)` calls
    take effect, or those loggers will go silent

    Returns:
        dict[str, Any]: Configuration dict in `logging.config.dictConfig` schema
    """
    pathlib.Path(DEFAULT_LOG_DIR).mkdir(parents=True, exist_ok=True)

    proc_name = multiprocessing.current_process().name

    logging_conf: dict[str, Any] = {
        'version':1,
        'disable_existing_loggers':True,
        'handlers':{
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'generic'
            },
            'file_daemon': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'generic',
                'filename': f"{DEFAULT_LOG_DIR}{proc_name}.log",
                'maxBytes': 10 * 1024 * 1024,  # 10 MBytes
                'backupCount': 4
            },
            'file_web_access': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'generic',
                'filename': f"{DEFAULT_LOG_DIR}webserver.access.log",
                'maxBytes': 10 * 1024 * 1024,  # 10 MBytes
                'backupCount': 4
            },
            'file_web_error': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'generic',
                'filename': f"{DEFAULT_LOG_DIR}webserver.error.log",
                'maxBytes': 10 * 1024 * 1024,  # 10 MBytes
                'backupCount': 4
            }
        },
        'formatters':{
            'generic': {
                'format': '[%(asctime)s][%(levelname)-8s] --- %(message)s (%(filename)s)',
                'datefmt': '%Y-%m-%d %H:%M:%S',
                'class': 'logging.Formatter'
            }
        },
        'loggers':{
            "__main__": {
                'level': str(get_log_level(minlevel="INFO")),
                'handlers': ['console', 'file_daemon'],
                'propagate': False
            },
            "cmdb": {
                'level': str(get_log_level()),
                'handlers': ['console', 'file_daemon'],
                'propagate': False
            },
            "gunicorn.error": {
                "level": "INFO",
                "handlers": ["file_web_error"],
                "propagate": False,
                "qualname": "gunicorn.error"
            },
            "gunicorn.access": {
                "level": "INFO",
                "handlers": ["file_web_access"],
                "propagate": False,
                "qualname": "gunicorn.access"
            }
        }
    }

    return logging_conf
