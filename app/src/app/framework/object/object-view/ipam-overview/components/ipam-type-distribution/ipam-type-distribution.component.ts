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
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    Input,
    OnChanges,
    OnDestroy,
    SimpleChanges,
    ViewChild
} from '@angular/core';

import {
    ArcElement,
    Chart,
    ChartConfiguration,
    DoughnutController,
    Tooltip,
    TooltipItem
} from 'chart.js';

import { IpamTypeDistributionEntry } from '../../models/ipam-overview.types';
import { getTypeDistributionColors } from './ipam-type-distribution.utils';
/* ------------------------------------------------------------------------------------------------------------------ */

Chart.register(DoughnutController, ArcElement, Tooltip);

interface ChartItemMeta {
    label: string;
    count: number;
    percentage: number;
    color: string;
}

@Component({
    selector: 'cmdb-ipam-type-distribution',
    templateUrl: './ipam-type-distribution.component.html',
    styleUrls: ['./ipam-type-distribution.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class IpamTypeDistributionComponent implements AfterViewInit, OnChanges, OnDestroy {

    @Input() public typeDistribution: IpamTypeDistributionEntry[] = [];
    @Input() public loading = false;
    @Input() public title = 'Distribution by Type';

    @ViewChild('chartCanvas') private chartCanvas?: ElementRef<HTMLCanvasElement>;

    public legendItems: ChartItemMeta[] = [];

    private chart: Chart<'doughnut'> | null = null;
    private viewReady = false;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngAfterViewInit(): void {
        this.viewReady = true;
        this.renderChart();
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['typeDistribution']) {
            this.buildMeta();
            if (this.viewReady) {
                this.renderChart();
            }
        }
    }

    public ngOnDestroy(): void {
        this.chart?.destroy();
        this.chart = null;
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get hasData(): boolean {
        return this.legendItems.length > 0;
    }

    public trackByLabel(_index: number, item: ChartItemMeta): string {
        return item.label;
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private buildMeta(): void {
        const items = this.typeDistribution ?? [];
        const colors = getTypeDistributionColors(items);

        this.legendItems = items.map((item, index) => ({
            label: item.label,
            count: item.count,
            percentage: item.percentage,
            color: colors[index]
        }));
    }

    private renderChart(): void {
        const canvas = this.chartCanvas?.nativeElement;
        if (!canvas) {
            return;
        }

        if (!this.hasData) {
            this.chart?.destroy();
            this.chart = null;
            return;
        }

        const config = this.buildConfig();

        if (this.chart) {
            this.chart.data = config.data;
            this.chart.options = config.options ?? {};
            this.chart.update();
            return;
        }

        this.chart = new Chart(canvas, config);
    }

    private buildConfig(): ChartConfiguration<'doughnut'> {
        const labels = this.legendItems.map(item => item.label);
        const data = this.legendItems.map(item => item.count);
        const backgroundColor = this.legendItems.map(item => item.color);
        const meta = this.legendItems;

        return {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor,
                    borderColor: '#ffffff',
                    borderWidth: 2,
                    hoverOffset: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '70%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            title: (items: TooltipItem<'doughnut'>[]) =>
                                items?.[0]?.label ?? '',
                            label: (item: TooltipItem<'doughnut'>) => {
                                const entry = meta[item.dataIndex];
                                if (!entry) {
                                    return '';
                                }
                                const percent = Number.isFinite(entry.percentage)
                                    ? entry.percentage.toFixed(2)
                                    : '0';
                                return ` ${entry.count} IPs (${percent}%)`;
                            }
                        }
                    }
                }
            }
        };
    }
}
