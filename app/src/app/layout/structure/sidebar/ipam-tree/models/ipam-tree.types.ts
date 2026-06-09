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

export type IpamNodeType = 'ipv4' | 'ipv6';

/**
 * Single node in the IPAM sidebar tree. Supernets carry `has_children` so the
 * tree knows whether to offer a (lazy-loaded) expand toggle; `children` is only
 * populated once a supernet has been expanded.
 */
export interface IpamTreeNode {
    public_id: number;
    name: string;
    cidr: string;
    type: IpamNodeType;
    has_children?: boolean;
    children?: IpamTreeNode[];
}

/**
 * Initial payload of `GET /rest/ipam/tree/`.
 */
export interface IpamTreeResponse {
    supernets: IpamTreeNode[];
    unassigned: IpamTreeNode[];
}

/**
 * Payload of `GET /rest/ipam/tree/supernets/<public_id>` returning the nested
 * child subtree of a single supernet.
 */
export interface IpamSupernetChildrenResponse {
    children: IpamTreeNode[];
}
