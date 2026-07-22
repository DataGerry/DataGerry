#!/bin/bash
# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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

# DATAGERRY setup

# define variables
DIR_ETC="/etc"
DIR_BIN="/usr/bin"
DIR_SYSTEMD="/etc/systemd/system"
DIR_TMPFILES="/usr/lib/tmpfiles.d"

# create user and group, if not exist
/usr/bin/getent group datagerry || /usr/sbin/groupadd -r datagerry
/usr/bin/getent passwd datagerry || /usr/sbin/useradd -r -d /home/datagerry -s /sbin/nologin -g datagerry datagerry

# create directories
mkdir -p ${DIR_ETC}/datagerry

# stop datagerry service
cp files/datagerry.service ${DIR_SYSTEMD}
systemctl daemon-reload
systemctl stop datagerry

# install files
cp files/cmdb.conf ${DIR_ETC}/datagerry
cp files/app-config.json ${DIR_ETC}/datagerry
cp files/datagerry ${DIR_BIN}
cp files/datagerry.conf ${DIR_TMPFILES}

# enable datagerry service
systemctl daemon-reload
systemctl enable datagerry
systemctl start datagerry
