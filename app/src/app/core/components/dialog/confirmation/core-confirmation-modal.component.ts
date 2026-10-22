import { Component, inject, Input } from '@angular/core';
import { FormControl } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
  selector: 'core-confirmation-modal',
  templateUrl: './core-confirmation-modal.component.html',
  styleUrls: ['./core-confirmation-modal.component.scss'],
  standalone: false
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
  /** When set, the user must type this text before confirming. */
  @Input() confirmationText: string = '';

  public readonly activeModal = inject(NgbActiveModal);
  public readonly confirmationControl = new FormControl('', { nonNullable: true });

  public get canConfirm(): boolean {
    return !this.confirmationText || this.confirmationControl.value.trim() === this.confirmationText;
  }

  confirm(): void {
    if (!this.canConfirm) {
      return;
    }

    this.activeModal.close('confirmed');
  }
}
