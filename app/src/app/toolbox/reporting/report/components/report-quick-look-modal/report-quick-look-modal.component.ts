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
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { CoreModule } from 'src/app/core/core.module';
import { CopyService } from 'src/app/core/services/copy.service';
import { ReportSentencePart, sentenceText } from '../filter-builder/report-filter-labels';
import { ReportSentenceComponent } from '../report-sentence/report-sentence.component';

/** Read-only view of what a report shows, opened from the reports overview. */
@Component({
    selector: 'app-report-quick-look-modal',
    standalone: true,
    imports: [CoreModule, ReportSentenceComponent],
    templateUrl: './report-quick-look-modal.component.html',
    styleUrls: ['./report-quick-look-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ReportQuickLookModalComponent {
    public readonly activeModal = inject(NgbActiveModal);
    private readonly copyService = inject(CopyService);

    /* Set by the opener before the first render. */
    public reportName = '';
    public typeLabel = '';
    public fieldCount = 0;
    public parts: ReportSentencePart[] = [];

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onCopy(): void {
        this.copyService.copyWithFeedback(sentenceText(this.parts), 'report description');
    }
}
