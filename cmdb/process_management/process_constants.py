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
The exit codes DataGerry ends with and how often its main thread looks at its services

The process a supervisor (systemd's ``Restart=on-failure``) watches is the main DataGerry process, so its exit code is
what decides a restart: 0 only after a requested stop (SIGTERM, Ctrl+C), 1 after a service crashed or could not start
"""
# -------------------------------------------------------------------------------------------------------------------- #

#: A requested stop: SIGTERM (``systemctl stop``) or SIGINT (Ctrl+C) - nothing to restart
EXIT_CODE_STOPPED: int = 0
#: A service crashed - its boot routine failed, gunicorn died - or could not be started: the supervisor restarts
EXIT_CODE_FAILED: int = 1
#: How long the main thread waits on one service before looking again; short, so a signal handler runs promptly
WAIT_POLL_SECONDS: float = 0.5
