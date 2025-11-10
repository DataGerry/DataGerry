/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input, AfterViewInit, AfterViewChecked, ViewChild } from '@angular/core';

import { BehaviorSubject } from 'rxjs';
// IMPORTANT
// chartjs-plugin-datalabel must be loaded after the Chart.js library!
import { Chart, registerables } from 'chart.js';
import ChartDataLabels from 'chartjs-plugin-datalabels';
Chart.register(...registerables);
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-charts',
    templateUrl: './charts.component.html',
    styleUrls: ['./charts.component.scss'],
    standalone: false
})
export class ChartsComponent implements AfterViewInit, AfterViewChecked {

  @ViewChild('chartcanvas', {static : false}) public chartRef;

  @Input() labelColors: any[];
  private chart;

  private labels = new BehaviorSubject<any[]>([]);

  @Input() set dataLabels(value: string[]) {
    this.labels?.next(value);
  }

    get dataLabels() {
        return this.labels?.getValue();
    }

    private items = new BehaviorSubject<any[]>([]);
    @Input() set dataItems(value: any[]) {
        this.items?.next(value);
    }

    get dataItems() {
        return this.items?.getValue();
    }
/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    ngAfterViewInit() {
        this.chart = new Chart(this.chartRef.nativeElement,
            {
                type: 'bar',
                data: {
                    labels: this.dataLabels,
                    datasets: [
                        {
                            data: this.dataItems,
                            backgroundColor: this.labelColors,
                            datalabels: {
                                color: '#FFF', font: { size: 15 }
                            }
                        }
                    ],
                },
                options: {
                    animation: false,
                    responsive: true,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            enabled: false
                        }
                    }
                },
                plugins: [ChartDataLabels],
            }
        );

        this.chart.update(true);
    }

    ngAfterViewChecked() {
        this.chart?.update(true);
    }
}
