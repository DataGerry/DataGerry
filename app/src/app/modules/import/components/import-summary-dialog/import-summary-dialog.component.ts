import { Component, inject, Input } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
    selector: 'app-import-summary-modal',
    templateUrl: './import-summary-modal.component.html',
    styleUrls: ['./import-summary-modal.component.scss'],
    standalone: false
})
export class ImportSummaryModalComponent {
    public readonly modal = inject(NgbActiveModal);

    @Input() summary: any;
}
