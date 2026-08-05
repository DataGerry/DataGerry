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

# small helper script for ansible dynamic inventory 

# config variables
DATAGERRY_EXPORT_TASK=ansible-router
DATAGERRY_REST_URL=http://127.0.0.1:4000/rest
DATAGERRY_REST_USER=admin
DATAGERRY_REST_PASSWORD=admin

# create output
if [ "$1" == "--list" ]
then
	# execute task
	curl \
		-X GET \
		-u "${DATAGERRY_REST_USER}:${DATAGERRY_REST_PASSWORD}" \
		--silent \
		${DATAGERRY_REST_URL}/exportdjob/pull/${DATAGERRY_EXPORT_TASK}
else
	echo "[]"
fi
