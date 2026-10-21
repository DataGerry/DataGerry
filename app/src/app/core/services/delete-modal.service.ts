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
import { Injectable, inject } from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { CoreDeleteConfirmationModalComponent } from '../components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { FullscreenModalService } from './fullscreen-modal.service';

/**
 * Configuration options for delete confirmation modal
 */
export interface DeleteModalConfig {
  /** The title of the modal */
  title: string;
  /** The type of item being deleted (e.g., 'Connector', 'Webhook') */
  itemType: string;
  /** The name of the item being deleted */
  itemName: string;
  /** Optional description for the modal */
  description?: string;
  /** Optional warning message to display */
  warningMessage?: string;
  /** Optional warning title (defaults to 'Warning:') */
  warningTitle?: string;
  /** Optional warning icon class (defaults to 'fas fa-exclamation-circle') */
  warningIconClass?: string;
  /** Callback function to execute when deletion is confirmed */
  onConfirm: () => void;
  /** Optional modal size (defaults to 'lg') */
  size?: 'sm' | 'lg' | 'xl';
}

/**
 * Service for handling delete confirmation modals
 */
@Injectable({
  providedIn: 'root'
})
export class DeleteModalService {

  private readonly fullscreenModalService = inject(FullscreenModalService);

  constructor(private modalService: NgbModal) { }

  /**
   * Opens a delete confirmation modal with the provided configuration
   * @param config Configuration for the delete confirmation modal
   * @returns Promise that resolves when the modal is closed
   */
  public confirmDelete(config: DeleteModalConfig): Promise<void> {
    // Hosted inside the fullscreen element while one is open; a body-level modal is not painted there.
    const modalRef = this.modalService.open(
      CoreDeleteConfirmationModalComponent,
      this.fullscreenModalService.withFullscreenContainer({
        size: config.size || 'lg',
        windowClass: 'dg-modal-window',
        backdropClass: 'dg-modal-window-backdrop'
      })
    );

    // Set component inputs
    modalRef.componentInstance.title = config.title;
    modalRef.componentInstance.itemType = config.itemType;
    modalRef.componentInstance.itemName = config.itemName;
    modalRef.componentInstance.description = config.description;
    modalRef.componentInstance.warningMessage = config.warningMessage;
    modalRef.componentInstance.warningTitle = config.warningTitle;
    modalRef.componentInstance.warningIconClass = config.warningIconClass;

    return modalRef.result.then(
      (result) => {
        if (result === 'confirmed') {
          config.onConfirm();
        }
      },
      () => {
        // Modal was dismissed, do nothing
      }
    );
  }
}
