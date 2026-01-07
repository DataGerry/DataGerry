/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { finalize } from 'rxjs/operators';

import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { OptionType } from 'src/app/toolbox/isms/models/option-type.enum';
import { ExtendableOption } from 'src/app/framework/models/object-group.model';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { CoreDeleteConfirmationModalComponent } from '../dialog/delete-dialog/core-delete-confirmation-modal.component';

const DEFAULT_MODAL_TITLE = 'Manage Options';

@Component({
    selector: 'app-extendable-option-manager',
    templateUrl: './extendable-option-manager.component.html',
    styleUrls: ['./extendable-option-manager.component.scss'],
    standalone: false
})
export class ExtendableOptionManagerComponent implements OnInit {
  /**
   * The OptionType to manage (e.g. OptionType.OBJECT_GROUP, OptionType.OWNER, etc.)
   */
  @Input() optionType!: OptionType;

  /**
   * The current list of items (extendable options) that the parent has, if any
   */
  @Input() options: ExtendableOption[] = [];

  /**
   * The title displayed in the modal header (e.g. "Manage Categories"). 
   * Defaults to "Manage Options".
   */
  @Input() modalTitle: string = DEFAULT_MODAL_TITLE;

  /**
   * The singular name for this item type, used in toast messages, placeholders, etc. 
   * e.g. "Category", "Status", "Tag", ...
   */
  @Input() itemLabel: string = 'Option';

  @Input() itemLabelPlural: string;

  /**
   * Fires when user closes the manager (so the parent can do any refresh if needed).
   */
  @Output() close = new EventEmitter<void>();

  // Internal copy for local edits
  public localOptions: ExtendableOption[] = [];
  public newItemValue = '';
  public editingItemId?: number;
  public editingItemValue = '';

  constructor(
    private extendableOptionService: ExtendableOptionService,
    private toast: ToastService,
    private loaderService: LoaderService,
    private modalService: NgbModal
  ) { }

  ngOnInit(): void {
    // Make a local copy so user can edit them freely
    this.localOptions = JSON.parse(JSON.stringify(this.options));
  }

  /**
   * Close (emit event so parent can do any refresh if needed)
   */
  public closeModal(): void {
    this.close.emit();
  }

  /**
   * Create a new item and add it to the local list
   */
  public onAddNewItem(): void {
    const val = this.newItemValue.trim();
    if (!val) { return; }

    this.loaderService.show();
    this.extendableOptionService.createExtendableOption(val, this.optionType, false)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (res) => {
          const created = (res as any).result || (res as any).raw;
          if (created?.public_id) {
            this.localOptions.push(created);
            this.toast.success(`${this.itemLabel} "${val}" created`);
            this.newItemValue = '';
          }
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Begin editing an existing item
   */
  public onEditItem(item: ExtendableOption): void {
    this.editingItemId = item.public_id;
    this.editingItemValue = item.value;
  }

  /**
   * Cancel inline editing of item
   */
  public cancelEditItem(): void {
    this.editingItemId = undefined;
    this.editingItemValue = '';
  }

  /**
   * Save changes to an existing item
   */
  public saveEditItem(item: ExtendableOption): void {
    const newVal = (this.editingItemValue || '').trim();
    if (!newVal) {
      this.toast.warning(`${this.itemLabel} name cannot be empty`);
      return;
    }

    this.loaderService.show();
    const payload = {
      public_id: item.public_id,
      value: newVal,
      option_type: item.option_type,
      predefined: item.predefined
    };
    this.extendableOptionService.updateExtendableOption(item.public_id, payload)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: (resp: any) => {
          const updated = resp.result || resp.raw;
          if (updated?.public_id) {
            const idx = this.localOptions.findIndex(x => x.public_id === item.public_id);
            if (idx >= 0) {
              this.localOptions[idx].value = newVal;
            }
            this.toast.success(`${this.itemLabel} updated`);
            this.editingItemId = undefined;
            this.editingItemValue = '';
          }
        },
        error: (err: any) => {
          this.toast.error(err?.error?.message);
        }
      });
  }

  /**
   * Delete an item
   */
  public onDeleteItem(item: ExtendableOption): void {
    if (!item.public_id) { return; }

    const modalRef = this.modalService.open(CoreDeleteConfirmationModalComponent, { size: 'lg' });
    modalRef.componentInstance.title = `Delete ${this.itemLabel}`;
    modalRef.componentInstance.item = item;
    modalRef.componentInstance.itemType = this.itemLabel;
    modalRef.componentInstance.itemName = item.value;

    modalRef.result.then((result) => {
      if (result === 'confirmed') {
          this.deleteItem(item);
      }
    }, () => {});

  }

  private deleteItem(item: ExtendableOption) {
    this.loaderService.show();
    this.extendableOptionService.deleteExtendableOption(item.public_id)
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: () => {
          this.localOptions = this.localOptions.filter(c => c.public_id !== item.public_id);
          this.toast.success(`${this.itemLabel} deleted`);
        },
        error: (err) => {
          this.toast.error(err?.error?.message);
        }
      });
  }
}
