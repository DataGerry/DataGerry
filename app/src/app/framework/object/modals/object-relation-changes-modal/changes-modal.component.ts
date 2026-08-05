import { Component, Input, Output, EventEmitter } from '@angular/core';
import { RelationLog } from 'src/app/framework/services/relation-log.service';

@Component({
    selector: 'app-changes-modal',
    templateUrl: './changes-modal.component.html',
    styleUrls: ['./changes-modal.component.scss'],
    standalone: false
})
export class ChangesModalComponent {
  @Input() log: RelationLog;
  @Output() close = new EventEmitter<void>();

  objectKeys = Object.keys;

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