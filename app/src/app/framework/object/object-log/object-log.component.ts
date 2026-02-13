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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, OnInit, Renderer2, ChangeDetectorRef } from '@angular/core';
import { Location } from '@angular/common';
import { LogService } from '../../services/log.service';
import { ActivatedRoute } from '@angular/router';
import { CmdbLog } from '../../models/cmdb-log';
import { RenderResult } from '../../models/cmdb-render';
import { CmdbMode } from '../../modes.enum';
import { UntypedFormGroup } from '@angular/forms';

@Component({
    selector: 'cmdb-object-log',
    templateUrl: './object-log.component.html',
    styleUrls: ['./object-log.component.scss'],
    standalone: false
})
export class ObjectLogComponent implements OnInit {

    private logID: number;
    public log: CmdbLog;
    public completeLogList: CmdbLog[];
    public mode: CmdbMode.View;
    public renderForm: UntypedFormGroup;
    public compareForm: UntypedFormGroup;
    public renderResult: RenderResult;
    public compareResult: RenderResult;

    constructor(private logService: LogService, private activateRoute: ActivatedRoute, private render: Renderer2,
        private readonly changeDetectorRef: ChangeDetectorRef, private location: Location) {
        this.renderForm = new UntypedFormGroup({});
        this.compareForm = new UntypedFormGroup({});
        this.activateRoute.params.subscribe((params) => {
            this.logID = params.publicID;
        });
    }


    public ngOnInit(): void {
        this.logService.getLog(this.logID).subscribe((log: CmdbLog) => {
            this.log = log;
            this.renderResult = JSON.parse(this.log.render_state);
        },
            (error) => {
                // console.error(error);
            },
            () => {
                this.logService.getCorrespondingLogs(this.logID).subscribe((logs: CmdbLog[]) => {
                    this.completeLogList = logs;
                });
            });
    }


    ngAfterViewChecked(): void {
        this.changeDetectorRef.detectChanges();
    }


    public loadCompareRender(logID: number) {
        const selectedCompareLog: CmdbLog = this.completeLogList.filter(compareLog => compareLog.public_id == logID)[0];
        if (selectedCompareLog.render_state !== undefined) {
            this.compareForm = new UntypedFormGroup({});
            this.compareResult = JSON.parse(selectedCompareLog.render_state);
        }
        this.markDifferences();
    }


    private markDifferences() {
        const changedInField = this.renderResult.fields.filter(this.comparer(this.compareResult.fields));

        Object.keys(this.renderForm.controls).forEach(key => {
            const currentSelector = `input[name='${key}']`;
            document.querySelector(currentSelector).classList.remove('bg-success');
            document.querySelector(currentSelector).classList.remove('text-white');
            if (changedInField.some((item) => item.name === key)) {
                document.querySelector(currentSelector).classList.add('bg-success');
                document.querySelector(currentSelector).classList.add('text-white');
            }
        });
    }


    private comparer(otherArray) {
        return (current) => {
            return otherArray.filter((other) => {
                return other.value === current.value && other.name === current.name;
            }).length === 0;
        };
    }

    /**
     * Navigates back to the previous page in the browser's history.
     */
    goBack(): void {
        this.location.back();
    }

}