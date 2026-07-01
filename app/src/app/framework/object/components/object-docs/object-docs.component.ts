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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, inject, OnChanges, Input, SimpleChanges } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';

import { FileSaverService } from 'ngx-filesaver';
import { Observable } from 'rxjs';
import { take } from 'rxjs/operators';

import { DocapiService } from '../../../../modules/docapi/services/docapi.service';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';

import { RenderResult } from '../../../models/cmdb-render';
import { DocTemplate } from '../../../../modules/docapi/models/cmdb-doctemplate';
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-docs',
    templateUrl: './object-docs.component.html',
    styleUrls: ['./object-docs.component.scss'],
    standalone: false
})
export class ObjectDocsComponent implements OnChanges {

    @Input() renderResult: RenderResult;
    docs: DocTemplate[];

    private readonly docapiService = inject(DocapiService);
    private readonly fileSaverService = inject(FileSaverService);
    private readonly dialog = inject(MatDialog);
    private readonly premiumFeatureService = inject(PremiumFeatureService);

    /** Drives the "Pro" upsell state shown when the Document Generator is not covered by the license. */
    readonly documentGeneratorAvailable$: Observable<boolean> =
        this.premiumFeatureService.isAvailable$(LicenseFeature.DocumentGenerator);

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    ngOnChanges(changes: SimpleChanges) {
        if (changes.renderResult && this.renderResult) {
            this.loadDocuments(this.renderResult.type_information.type_id);
        }
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public downloadDocument(templateId: number, objectId: number, docName: string) {
        const filename = docName + '.pdf';

        this.docapiService.getRenderedObjectDoc(templateId, objectId).subscribe(res => this.saveFile(res, filename));
    }


    public saveFile(data: any, filename: string) {
        this.fileSaverService.save(data.body, filename);
    }


    public promptDocumentUpgrade(): void {
        this.premiumFeatureService.promptUpgrade(LicenseFeature.DocumentGenerator);
    }


    openDocumentDialog(): void {
        const dialogRef = this.dialog.open(ObjectDocsComponent, {
            width: '400px',
            data: { docs: this.docs }
        });

        dialogRef.afterClosed().subscribe(result => {
        });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Skips the template lookup when the feature is locked, so we never fire a call the edition can't serve. */
    private loadDocuments(typeId: number): void {
        this.premiumFeatureService.isAvailable$(LicenseFeature.DocumentGenerator)
            .pipe(take(1))
            .subscribe((available: boolean) => {
                if (!available) {
                    this.docs = [];
                    return;
                }

                this.docapiService.getObjectDocTemplateList(typeId)
                    .subscribe((docs: DocTemplate[]) => {
                        this.docs = docs;
                    });
            });
    }
}
