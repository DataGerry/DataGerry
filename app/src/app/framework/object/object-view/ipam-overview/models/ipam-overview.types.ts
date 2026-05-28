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
    used_ips: number;
    free_ips: number;
    usage_percent: number;
    parent_id: number | null;
    has_children: boolean;
}

export interface IpamSupernetSubnetPage {
    page: number;
    page_size: number;
    total: number;
    rows: IpamSubnetSummary[];
}

export interface IpamSupernetOverviewResponse {
    supernet: IpamSupernetSummary;
    subnets: IpamSupernetSubnetPage;
}

export interface IpamSupernetChildrenResponse {
    parent: { public_id: number };
    rows: IpamSubnetSummary[];
}

export interface IpamSupernetOverviewParams {
    page?: number;
    page_size?: number;
    sort?: string;
    order?: number;
    search?: string;
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
    ip_range?: IpamIpRange;
    total_ips?: number;
    assignable_ips?: number;
    used_ips?: number;
    free_ips?: number;
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
    ci_explorer_color?: string | null;
    count: number;
    percentage: number;
}

export interface IpamIpDistributionSector {
    ip_start: string;
    ip_end: string;
    used_count: number;
    percentage: number;
}

export interface IpamIpDistributionRange {
    ip_start: string;
    ip_end: string;
    sectors: IpamIpDistributionSector[];
}

export interface IpamIpDistribution {
    sector_size: number;
    ranges: IpamIpDistributionRange[];
}

export interface IpamSubnetOverviewResponse {
    subnet: IpamSubnetDetail;
    ips: IpamIpListPage;
    type_distribution?: IpamTypeDistributionEntry[];
    ip_distribution?: IpamIpDistribution | null;
}

export interface IpamSubnetOverviewParams {
    page?: number;
    page_size?: number;
    sort?: string;
    order?: number;
}
