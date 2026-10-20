import { Component, inject, Input } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { RelationLog } from 'src/app/framework/services/relation-log.service';

@Component({
    selector: 'app-changes-modal',
    templateUrl: './changes-modal.component.html',
    styleUrls: ['./changes-modal.component.scss'],
    standalone: false
})
export class ChangesModalComponent {
  @Input() log: RelationLog;

  objectKeys = Object.keys;

  public readonly activeModal = inject(NgbActiveModal);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  hasCreateChanges(): boolean {
    return this.log?.action === 'CREATE' && 
           this.log.changes && 
           Object.keys(this.log.changes).length > 0;
  }

  hasEditChanges(): boolean {
    return this.log?.action === 'EDIT' &&
           this.log.changes?.modified &&
           Object.keys(this.log.changes.modified).length > 0;
  }
}
