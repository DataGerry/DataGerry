Name:       DATAGERRY
Version:	@@DG_BUILDVAR_VERSION@@
Release:	1%{?dist}
Summary:	DATAGERRY is an enterprise-grade OpenSource CMDB, which completely leaves the definition of object types to the user.

Group:		Applications/Databases
License:	AGPLv3
URL:		https://www.datagerry.com
Vendor:     becon GmbH
Source0:	https://github.com/DATAGERRY/DATAGERRY
BuildRequires: systemd

%description
A CMDB is a database which includes all informations about objects 
(i.e. servers, routers, locations, maintenance contracts), that are 
required for operating an IT infrastructure. Also the relationships 
between objects are stored (i.e. server a is placed on location b). 
Available solutions tend to be shipped with predefined object types, 
that often can only be customized with big efforts.

DATAGERRY is an enterprise-grade OpenSource CMDB, where object types
can be completely defined by the user and can be adapted at runtime. 
The stored data can be used in different ways, i.e. for automated 
export to external systems, an intelligent search within the data, 
or a reporting. All functions are implemented with the generic and 
the custom definition of object types in mind. With a plugin system, 
DATAGERRY can be extended easily - also by experienced users.


%pre
if [ $1 == 1 ];then
   echo "-----------------------"
   echo "New installation"
   echo "-----------------------"
   systemctl start mongod || true
   systemctl enable mongod || true
   /usr/bin/getent group datagerry || /usr/sbin/groupadd -r datagerry || true
   /usr/bin/getent passwd datagerry || /usr/sbin/useradd -r -d /home/datagerry -s /sbin/nologin -g datagerry datagerry || true

elif [ $1 == 2 ];then
   echo "-----------------------"
   echo "Update installation"
   echo "-----------------------"
   pkill datagerr+ || true
   systemctl stop rabbitmq-server || true
   systemctl disable rabbitmq-server || true

   if [ -e /etc/datagerry/cmdb.conf ]; then
      cp /etc/datagerry/cmdb.conf /etc/datagerry/cmdb.conf.dg_old || true
   fi
   if [ -e /etc/datagerry/app-config.json ]; then
      cp /etc/datagerry/app-config.json /etc/datagerry/app-config.json.dg_old || true
   fi
fi


%install
mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_unitdir}
mkdir -p %{buildroot}%{_tmpfilesdir}
mkdir -p %{buildroot}%{_sysconfdir}/datagerry
install %{_sourcedir}/datagerry %{buildroot}%{_bindir}/datagerry
install %{_sourcedir}/datagerry.service %{buildroot}%{_unitdir}/datagerry.service
install %{_sourcedir}/datagerry.conf %{buildroot}%{_tmpfilesdir}/datagerry.conf
install -D %{_sourcedir}/cmdb.conf %{buildroot}%{_sysconfdir}/datagerry/cmdb_default.conf
install -D %{_sourcedir}/app-config.json %{buildroot}%{_sysconfdir}/datagerry/app-config_default.json


%files
%{_bindir}/datagerry
%{_unitdir}/datagerry.service
%{_tmpfilesdir}/datagerry.conf
%{_sysconfdir}/datagerry/cmdb_default.conf
%{_sysconfdir}/datagerry/app-config_default.json

%posttrans
if [ ! -f /etc/datagerry/cmdb.conf ]; then
   if [ -e /etc/datagerry/cmdb.conf.dg_old ]; then
      mv /etc/datagerry/cmdb.conf.dg_old /etc/datagerry/cmdb.conf || true
   else
      cp /etc/datagerry/cmdb_default.conf /etc/datagerry/cmdb.conf || true
   fi
fi

if [ ! -f /etc/datagerry/app-config.json ]; then
    if [ -e /etc/datagerry/app-config.json.dg_old ]; then
       mv /etc/datagerry/app-config.json.dg_old /etc/datagerry/app-config.json || true
    else
       cp /etc/datagerry/app-config_default.json /etc/datagerry/app-config.json || true
    fi
fi

systemctl daemon-reload || true
systemctl enable datagerry.service || true
systemctl start datagerry.service || true

%changelog
* @@DG_BUILDVAR_DATE@@ becon GmbH
- created
