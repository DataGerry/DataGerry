import { Component, Input } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
    selector: 'core-delete-confirmation-modal',
    templateUrl: './core-delete-confirmation-modal.component.html',
    standalone: false
})
export class CoreDeleteConfirmationModalComponent {
  @Input() title: string;
  @Input() item: any;
  @Input() itemType: string;
  @Input() itemName: string;
  @Input() description: string;
  @Input() warningTitle: string = 'Warning:';
  @Input() warningMessage: string = '';
  @Input() warningIconClass: string = 'fas fa-exclamation-circle';
  
  constructor(public activeModal: NgbActiveModal) { }

  confirmDelete(): void {
    this.activeModal.close('confirmed');
  }
}