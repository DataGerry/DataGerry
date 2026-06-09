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
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import {
    IpamIpDistribution,
    IpamIpDistributionRange,
    IpamIpDistributionSector,
    IpamSectorTypeStat,
    IpamTypeDistributionEntry
} from '../../models/ipam-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

const UNKNOWN_TYPE_COLOR = '#9CA3AF';
const FREE_TYPE_LABEL = 'free';
const MIN_SECTOR_ALPHA = 0.2;

interface IpamDistributionLegendItem {
    label: string;
    color: string;
}

interface IpamDistributionSectorView {
    key: string;
    isEmpty: boolean;
    color: string | null;
    label: string;
}

interface IpamDistributionRangeView {
    key: string;
    label: string;
    sectors: IpamDistributionSectorView[];
}

@Component({
    selector: 'cmdb-ipam-ip-distribution',
    templateUrl: './ipam-ip-distribution.component.html',
    styleUrls: ['./ipam-ip-distribution.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamIpDistributionComponent {

    public readonly ipDistribution = input<IpamIpDistribution | null>(null);
    public readonly typeDistribution = input<IpamTypeDistributionEntry[]>([]);
    public readonly loading = input(false);
    public readonly title = input('IP Distribution');
    public readonly activeSectorStart = input<string | null>(null);

    public readonly sectorSelect = output<string>();

    public readonly rangeViews = computed<IpamDistributionRangeView[]>(() => this.buildRangeViews());
    public readonly hasDistribution = computed(() => this.rangeViews().length > 0);
    public readonly legendItems = computed<IpamDistributionLegendItem[]>(() => this.buildLegend());

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onSectorSelect(sector: IpamDistributionSectorView): void {
        this.sectorSelect.emit(sector.key);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private buildRangeViews(): IpamDistributionRangeView[] {
        const distribution = this.ipDistribution();
        const ranges = distribution?.ranges ?? [];
        const sectorSize = distribution?.sector_size ?? 0;

        return ranges.map(range => ({
            key: range.ip_start,
            label: this.formatRangeLabel(range),
            sectors: (range.sectors ?? []).map(sector => this.buildSectorView(sector, sectorSize))
        }));
    }


    private buildSectorView(sector: IpamIpDistributionSector, sectorSize: number): IpamDistributionSectorView {
        const isEmpty = sector.used_count <= 0;
        const dominant = isEmpty ? null : this.getDominantType(sector);
        const color = dominant
            ? this.applyAlpha(dominant.ci_explorer_color || UNKNOWN_TYPE_COLOR, this.computeAlpha(sector.percentage))
            : null;

        return {
            key: sector.ip_start,
            isEmpty,
            color,
            label: this.buildSectorLabel(sector, sectorSize, dominant)
        };
    }


    private buildSectorLabel(
        sector: IpamIpDistributionSector,
        sectorSize: number,
        dominant: IpamSectorTypeStat | null
    ): string {
        const range = `${sector.ip_start} - ${sector.ip_end}`;
        const denominator = sectorSize > 0 ? sectorSize : Math.max(sector.used_count, 1);
        const usage = `${sector.used_count} of ${denominator} IPs used`;

        if (!dominant) {
            return `${range}: ${usage}`;
        }

        return `${range}: ${usage} — dominant: ${dominant.label} (${dominant.count})`;
    }


    private formatRangeLabel(range: IpamIpDistributionRange): string {
        const lastDot = range.ip_end.lastIndexOf('.');
        const endTail = lastDot >= 0 ? range.ip_end.substring(lastDot) : range.ip_end;
        return `${range.ip_start} - ${endTail}`;
    }


    private getDominantType(sector: IpamIpDistributionSector): IpamSectorTypeStat | null {
        const stats = sector.type_stats ?? [];
        if (stats.length === 0) {
            return null;
        }

        let dominant: IpamSectorTypeStat | null = null;
        for (const stat of stats) {
            if (!dominant || stat.count > dominant.count) {
                dominant = stat;
            }
        }
        return dominant;
    }


    private computeAlpha(percentage: number): number {
        if (!Number.isFinite(percentage) || percentage <= 0) {
            return MIN_SECTOR_ALPHA;
        }
        const ratio = percentage / 100;
        return Math.min(Math.max(ratio, MIN_SECTOR_ALPHA), 1);
    }


    private applyAlpha(hex: string, alpha: number): string {
        const rgb = this.hexToRgb(hex);
        if (!rgb) {
            return hex;
        }
        const safeAlpha = Math.round(alpha * 1000) / 1000;
        return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${safeAlpha})`;
    }


    private hexToRgb(hex: string): { r: number; g: number; b: number } | null {
        const normalized = hex?.trim().replace(/^#/, '');
        if (!normalized) {
            return null;
        }

        const expanded = normalized.length === 3
            ? normalized.split('').map(char => char + char).join('')
            : normalized;

        if (expanded.length !== 6 || /[^0-9a-fA-F]/.test(expanded)) {
            return null;
        }

        return {
            r: parseInt(expanded.substring(0, 2), 16),
            g: parseInt(expanded.substring(2, 4), 16),
            b: parseInt(expanded.substring(4, 6), 16)
        };
    }


    private buildLegend(): IpamDistributionLegendItem[] {
        const entries = this.typeDistribution() ?? [];
        const seen = new Set<string>();
        const items: IpamDistributionLegendItem[] = [];

        for (const entry of entries) {
            if (!entry || entry.count <= 0) {
                continue;
            }

            const label = entry.label?.trim();
            if (!label || label.toLowerCase() === FREE_TYPE_LABEL) {
                continue;
            }

            const key = label.toLowerCase();
            if (seen.has(key)) {
                continue;
            }
            seen.add(key);

            items.push({
                label,
                color: entry.ci_explorer_color || UNKNOWN_TYPE_COLOR
            });
        }

        return items;
    }
}
