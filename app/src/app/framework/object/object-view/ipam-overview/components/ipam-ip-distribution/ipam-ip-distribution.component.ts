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
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import {
    IpamIpDistribution,
    IpamIpDistributionRange,
    IpamIpDistributionSector
} from '../../models/ipam-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

const MINIMUM_DISTRIBUTION_SECTORS = 64;

@Component({
    selector: 'cmdb-ipam-ip-distribution',
    templateUrl: './ipam-ip-distribution.component.html',
    styleUrls: ['./ipam-ip-distribution.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamIpDistributionComponent {

    public readonly ipDistribution = input<IpamIpDistribution | null>(null);
    public readonly loading = input(false);
    public readonly title = input('IP Distribution');

    public readonly ranges = computed(() => this.ipDistribution()?.ranges ?? []);
    public readonly sectorsPerRange = computed(() => this.getSectorsPerRange());
    public readonly hasDistribution = computed(() => this.ranges().length > 0);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public trackByRange(_index: number, range: IpamIpDistributionRange): string {
        return range.ip_start;
    }


    public trackBySector(_index: number, sector: IpamIpDistributionSector): string {
        return sector.ip_start;
    }


    public isSectorEmpty(sector: IpamIpDistributionSector): boolean {
        return sector.used_count <= 0;
    }


    public isSectorLowUsage(sector: IpamIpDistributionSector): boolean {
        const percentage = this.normalizePercentage(sector.percentage);
        return !this.isSectorEmpty(sector) && percentage < 35;
    }


    public isSectorMediumUsage(sector: IpamIpDistributionSector): boolean {
        const percentage = this.normalizePercentage(sector.percentage);
        return percentage >= 35 && percentage < 70;
    }


    public isSectorHighUsage(sector: IpamIpDistributionSector): boolean {
        const percentage = this.normalizePercentage(sector.percentage);
        return percentage >= 70 && percentage < 100;
    }


    public isSectorFull(sector: IpamIpDistributionSector): boolean {
        return this.normalizePercentage(sector.percentage) >= 100;
    }


    public getSectorLabel(sector: IpamIpDistributionSector): string {
        const percentage = this.normalizePercentage(sector.percentage);
        const sectorSize = this.ipDistribution()?.sector_size ?? this.getSectorSize(sector);

        return `${sector.ip_start} - ${sector.ip_end}: ${sector.used_count} of ${sectorSize} IPs used (${percentage}%)`;
    }


    public formatRangeLabel(range: IpamIpDistributionRange): string {
        const lastDot = range.ip_end.lastIndexOf('.');
        const endTail = lastDot >= 0 ? range.ip_end.substring(lastDot) : range.ip_end;
        return `${range.ip_start} - ${endTail}`;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private getSectorsPerRange(): number {
        const maxSectorCount = Math.max(...this.ranges().map(range => range.sectors?.length ?? 0), 0);
        return maxSectorCount || MINIMUM_DISTRIBUTION_SECTORS;
    }


    private getSectorSize(sector: IpamIpDistributionSector): number {
        const start = this.lastOctet(sector.ip_start);
        const end = this.lastOctet(sector.ip_end);
        if (start == null || end == null) {
            return 0;
        }
        return Math.max(end - start + 1, 0);
    }


    private lastOctet(ip: string): number | null {
        const lastDot = ip?.lastIndexOf('.') ?? -1;
        if (lastDot < 0) {
            return null;
        }
        const value = Number(ip.substring(lastDot + 1));
        return Number.isFinite(value) ? value : null;
    }


    private normalizePercentage(value: number | null | undefined): number {
        if (value == null || !Number.isFinite(value)) {
            return 0;
        }

        return Math.min(Math.max(Math.round(value), 0), 100);
    }
}
