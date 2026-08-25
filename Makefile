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

# set environment variables
BUILDVAR_VERSION = 3.3.0
BIN_PYINSTALLER = pyinstaller
DATEVAR := $(shell date '+%a %b %d %Y')

# Sphinx (built for publishing to docs.datagerry.com, see release.yml)
BIN_SPHINX = sphinx-build
DIR_DOCS_SOURCE = docs/source
DIR_DOCS_BUILD = ${DIR_BUILD}/docs

BIN_PYTEST = pytest
BIN_PIP = pip
BIN_NPM = npm
BIN_YARN = yarn
BIN_RPMBUILD = rpmbuild
DIR_BUILD = $(CURDIR)/target
DIR_BIN_BUILD = ${DIR_BUILD}/bin
DIR_TEMP= ${DIR_BUILD}/temp

DIR_RPM_BUILD = ${DIR_BUILD}/rpm
DIR_DEB_BUILD = ${DIR_BUILD}/deb
DIR_ZIP_BUILD = ${DIR_BUILD}/zip
DIR_DOCKER_BUILD = ${DIR_BUILD}/docker
DIR_WEB_SOURCE = app
DIR_WEB_BUILD = app/dist/datagerry-app/browser
DIR_WEB_TARGET = cmdb/interface/net_app/datagerry-app
DIR_FRONTEND_BUILD = app/dist/datagerry-app/browser
DIR_FRONTEND_TARGET = ${DIR_BUILD}/frontend

# set default goal
.DEFAULT_GOAL := all

# build whole application
.PHONY: all
all: bin docs zip deb frontend docker


# install Python requirements
.PHONY: requirements
requirements:
	${BIN_PIP} install -r requirements.txt


# substitue BUILD variables
.PHONY: buildvars
buildvars:
	sed -i 's/@@DG_BUILDVAR_VERSION@@/${BUILDVAR_VERSION}/g' cmdb/__init__.py
	sed -i 's/@@DG_BUILDVAR_VERSION@@/${BUILDVAR_VERSION}/g' docs/source/conf.py


# create documentation (published to docs.datagerry.com from ${DIR_DOCS_BUILD} by release.yml)
.PHONY: docs
docs: requirements buildvars
	${BIN_SPHINX} -b html -a ${DIR_DOCS_SOURCE} ${DIR_DOCS_BUILD}


# create webapp
.PHONY: webapp
webapp:
#	cd ${DIR_WEB_SOURCE} && ${BIN_NPM} install
#	cd ${DIR_WEB_SOURCE} && ${BIN_NPM} run prod
	${BIN_NPM} install --legacy-peer-deps --prefix ${DIR_WEB_SOURCE}
	${BIN_NPM} run prod --prefix ${DIR_WEB_SOURCE}
	cp -R ${DIR_WEB_BUILD}/* ${DIR_WEB_TARGET}


# create frontend
.PHONY: frontend
frontend:
	mkdir -p ${DIR_FRONTEND_TARGET}
	${BIN_YARN}
	${BIN_YARN} --cwd $(CURDIR)/${DIR_WEB_SOURCE} build
	cp -R ${DIR_FRONTEND_BUILD}/* ${DIR_FRONTEND_TARGET}


# create onefile binary of DataGerry
.PHONY: bin
bin: requirements buildvars webapp
		-rm -rf ${DIR_BIN_BUILD}
		${BIN_PYINSTALLER} --name datagerry --onefile \
		--distpath ${DIR_BIN_BUILD} \
		--workpath ${DIR_TEMP} \
		--hidden-import cmdb.database.updater.versions.updater_20250619 \
		--hidden-import cmdb.database.updater.versions.updater_20251203 \
		--hidden-import cmdb.database.updater.versions.updater_20260225 \
		--hidden-import cmdb.database.updater.versions.updater_20260226 \
		--hidden-import cmdb.database.updater.versions.updater_20260417 \
		--hidden-import cmdb.database.updater.versions.updater_20260604 \
		--hidden-import cmdb.database.updater.versions.updater_20260720 \
		--hidden-import cmdb.database.updater.versions.updater_20260731 \
		--hidden-import cmdb.database.updater.versions.updater_20260804 \
		--hidden-import cmdb.database.updater.versions.updater_20260824 \
		--hidden-import cmdb.framework.exporter \
		--hidden-import cmdb.framework.exporter.format \
		--hidden-import cmdb.interface.gunicorn \
		--hidden-import gunicorn.glogging \
		--hidden-import gunicorn.workers.sync \
		--hidden-import reportlab.graphics.barcode.common \
		--hidden-import reportlab.graphics.barcode.code128 \
		--hidden-import reportlab.graphics.barcode.code93 \
		--hidden-import reportlab.graphics.barcode.code39 \
		--hidden-import reportlab.graphics.barcode.usps \
		--hidden-import reportlab.graphics.barcode.usps4s \
		--hidden-import reportlab.graphics.barcode.ecc200datamatrix \
		--add-data cmdb/interface/net_app/datagerry-app:cmdb/interface/net_app/datagerry-app \
		cmdb/__main__.py


# create RPM package
.PHONY: rpm
rpm: bin
	-rm -rf ${DIR_RPM_BUILD}
	mkdir -p ${DIR_RPM_BUILD}
	mkdir -p ${DIR_RPM_BUILD}/SOURCES
	cp ${DIR_BIN_BUILD}/datagerry ${DIR_RPM_BUILD}/SOURCES
	cp contrib/systemd/datagerry.service ${DIR_RPM_BUILD}/SOURCES
	cp etc/cmdb.conf ${DIR_RPM_BUILD}/SOURCES
	cp etc/app-config.json ${DIR_RPM_BUILD}/SOURCES
	cp contrib/tmpfiles.d/datagerry.conf ${DIR_RPM_BUILD}/SOURCES
	cp contrib/rpm/datagerry.spec ${DIR_RPM_BUILD}
	sed -i 's/@@DG_BUILDVAR_VERSION@@/$(subst -,_,${BUILDVAR_VERSION})/g' ${DIR_RPM_BUILD}/datagerry.spec
	sed -i "s/@@DG_BUILDVAR_DATE@@/${DATEVAR}/g" ${DIR_RPM_BUILD}/datagerry.spec
	${BIN_RPMBUILD} --define '_topdir ${DIR_RPM_BUILD}' -bb ${DIR_RPM_BUILD}/datagerry.spec


# create zip package
.PHONY: zip
zip: bin
	-rm -rf ${DIR_ZIP_BUILD}
	mkdir -p ${DIR_ZIP_BUILD}
	mkdir -p ${DIR_ZIP_BUILD}/src/datagerry/
	mkdir -p ${DIR_ZIP_BUILD}/src/datagerry/files
	cp ${DIR_BIN_BUILD}/datagerry ${DIR_ZIP_BUILD}/src/datagerry/files
	cp contrib/systemd/datagerry.service ${DIR_ZIP_BUILD}/src/datagerry/files
	cp contrib/tmpfiles.d/datagerry.conf ${DIR_ZIP_BUILD}/src/datagerry/files
	cp etc/cmdb.conf ${DIR_ZIP_BUILD}/src/datagerry/files
	cp etc/app-config.json ${DIR_ZIP_BUILD}/src/datagerry/files
	cp LICENSE ${DIR_ZIP_BUILD}/src/datagerry
	cp contrib/setup/setup.sh ${DIR_ZIP_BUILD}/src/datagerry
	#tar -czvf ${DIR_ZIP_BUILD}/datagerry-${BUILDVAR_VERSION}.tar.gz -C ${DIR_ZIP_BUILD}/src datagerry
	cd ${DIR_ZIP_BUILD}/src && zip -r ${DIR_ZIP_BUILD}/DataGerry-${BUILDVAR_VERSION}.zip *

# create deb package
.PHONY: deb
deb: bin
	-rm -rf ${DIR_DEB_BUILD}
	mkdir -p ${DIR_DEB_BUILD}
	mkdir -p ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/DEBIAN
	mkdir -p ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/usr/bin
	mkdir -p ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/usr/lib/systemd/system
	mkdir -p ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/usr/lib/tmpfiles.d
	mkdir -p ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/etc/datagerry
	cp contrib/deb/* ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/DEBIAN
	chmod 755 ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/DEBIAN/*
	sed -i 's/@@DG_BUILDVAR_VERSION@@/$(subst -,_,${BUILDVAR_VERSION})/g' ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/DEBIAN/control
	cp ${DIR_BIN_BUILD}/datagerry ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/usr/bin
	cp contrib/systemd/datagerry.service ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/usr/lib/systemd/system
	cp etc/cmdb.conf ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/etc/datagerry/
	cp etc/app-config.json ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/etc/datagerry/
	cp contrib/tmpfiles.d/datagerry.conf ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/usr/lib/tmpfiles.d
	chmod 755 ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/usr/*
	chmod 755 ${DIR_DEB_BUILD}/DataGerry_${BUILDVAR_VERSION}_all/etc/*
	cd ${DIR_DEB_BUILD} && dpkg-deb --build DataGerry_${BUILDVAR_VERSION}_all

# create Docker image
.PHONY: docker
docker: bin frontend
	mkdir -p ${DIR_DOCKER_BUILD}
	mkdir -p ${DIR_DOCKER_BUILD}/src
	mkdir -p ${DIR_DOCKER_BUILD}/src/files
	mkdir -p ${DIR_DOCKER_BUILD}/src/files/backend
	mkdir -p ${DIR_DOCKER_BUILD}/src/files/frontend
	mkdir -p ${DIR_DOCKER_BUILD}/src/files/conf
	cp contrib/docker/DockerfileBackend ${DIR_DOCKER_BUILD}/src
	cp contrib/docker/DockerfileFrontend ${DIR_DOCKER_BUILD}/src
	cp ${DIR_BIN_BUILD}/datagerry ${DIR_DOCKER_BUILD}/src/files/backend
	cp etc/cmdb.conf ${DIR_DOCKER_BUILD}/src/files/conf
	cp etc/app-config.json ${DIR_DOCKER_BUILD}/src/files/conf
	cp -r ${DIR_FRONTEND_TARGET} ${DIR_DOCKER_BUILD}/src/files
	docker build -f ${DIR_DOCKER_BUILD}/src/DockerfileFrontend -t becongmbh/datagerry-frontend:${BUILDVAR_VERSION} -t becongmbh/datagerry-frontend:latest ${DIR_DOCKER_BUILD}/src --no-cache &> build.log
	docker build -f ${DIR_DOCKER_BUILD}/src/DockerfileBackend -t becongmbh/datagerry-backend:${BUILDVAR_VERSION} -t becongmbh/datagerry-backend:latest ${DIR_DOCKER_BUILD}/src --no-cache

# execute tests
.PHONY: tests
tests: requirements
	${BIN_PYTEST} tests


# clean environment
.PHONY: clean
clean:
	rm -Rf ${DIR_BUILD}
	rm -Rf ${DIR_WEB_TARGET}/*
	rm -f datagerry.spec