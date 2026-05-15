/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

export interface IpamIpRange {
    first: string;
    last: string;
}

export interface IpamSupernetSummary {
    public_id: number;
    cidr: string;
    ip_range: IpamIpRange;
    total_ips: number;
    used_ips: number;
    free_ips: number;
    used_percent: number;
    free_percent: number;
    utilization_percent: number;
    subnet_count: number;
}

export interface IpamSubnetSummary {
    public_id: number;
    cidr: string;
    ip_range: IpamIpRange;
    used_ips: number;
    free_ips: number;
    usage_percent: number;
    parent_id: number | null;
}

export interface IpamSupernetOverviewResponse {
    supernet: IpamSupernetSummary;
    subnets: IpamSubnetSummary[];
}


/* ------------------------------------------------- SUBNET OVERVIEW ------------------------------------------------ */

export type IpamIpStatus = 'used' | 'free' | 'assigned' | 'reserved' | string;

export interface IpamTypeInfo {
    public_id: number;
    label: string;
}

export interface IpamAssignedTo {
    public_id: number;
    summary_line: string;
}

export interface IpamIpEntry {
    ip: string;
    status: IpamIpStatus;
    type_info: IpamTypeInfo | null;
    assigned_to: IpamAssignedTo | null;
    mac_address: string | null;
    last_seen?: string | null;
}

export interface IpamSubnetDetail {
    public_id?: number;
    cidr?: string;
    subnetmask?: string;
    ip_range?: IpamIpRange;
    total_ips?: number;
    used_ips?: number;
    free_ips?: number;
    used_percent?: number;
    free_percent?: number;
}

export interface IpamIpListPage {
    page: number;
    page_size: number;
    total: number;
    rows: IpamIpEntry[];
}

export interface IpamTypeDistributionEntry {
    public_id: number | null;
    label: string;
    count: number;
    percentage: number;
}

export interface IpamSubnetOverviewResponse {
    subnet: IpamSubnetDetail;
    ips: IpamIpListPage;
    type_distribution?: IpamTypeDistributionEntry[];
}

export interface IpamSubnetOverviewParams {
    page?: number;
    page_size?: number;
    sort?: string;
    order?: number;
}
