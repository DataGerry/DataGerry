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
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { finalize } from 'rxjs';

import { DocapiService } from '../../services/docapi.service';

import { DocTemplate } from '../../models/cmdb-doctemplate';
import { CmdbMode } from '../../../../framework/modes.enum';
import { LoaderService } from 'src/app/core/services/loader.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-docapi-template-edit',
    templateUrl: './docapi-edit.component.html',
    styleUrls: ['./docapi-edit.component.scss'],
    standalone: false
})
export class DocapiEditComponent implements OnInit {
    public docId: number;
    public docInstance: DocTemplate;
    public mode: number = CmdbMode.Edit;
    public templateLabel: string = '';
    public isLoading$ = this.loaderService.isLoading$;


    constructor(
        private docapiService: DocapiService,
        private route: ActivatedRoute,
        private loaderService: LoaderService
    ) {
        this.route?.params?.subscribe((id) => this.docId = id?.publicId);
    }


    public ngOnInit(): void {
        this.loaderService.show();
        this.docapiService?.getDocTemplate(this.docId).pipe(
            finalize(() => this.loaderService.hide())
        ).subscribe((docInstance: DocTemplate) => {
            this.docInstance = docInstance;
            this.templateLabel = docInstance?.label?.trim() ?? '';
        });
    }

    public onLabelChanged(label: string): void {
        this.templateLabel = label?.trim() ?? '';
    }

    public get title(): string {
        return this.templateLabel ? `Edit ${this.templateLabel} Template` : 'Edit Template';
    }
}
