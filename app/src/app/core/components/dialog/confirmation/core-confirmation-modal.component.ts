import { Component, Input } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'core-confirmation-modal',
  templateUrl: './core-confirmation-modal.component.html'
})
export class CoreConfirmationModalComponent {
  @Input() title: string;
  @Input() message: string;
  @Input() confirmButtonText: string = 'Confirm';
  @Input() cancelButtonText: string = 'Cancel';
  @Input() confirmButtonClass: string = 'btn-primary';
  @Input() warningTitle: string = 'Warning:';
  @Input() warningMessage: string = '';
  @Input() warningIconClass: string = 'fas fa-exclamation-circle';
  
  constructor(public activeModal: NgbActiveModal) { }

  confirm(): void {
    this.activeModal.close('confirmed');
  }
}
