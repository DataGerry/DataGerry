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
import { ChangeDetectionStrategy, Component, EventEmitter, Output } from '@angular/core';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Accessible drag-and-drop / browse file picker.
 *
 * Emits the chosen file only; the parent owns the selected-file display and validity.
 */
@Component({
  selector: 'cmdb-license-import',
  templateUrl: './license-import.component.html',
  styleUrls: ['./license-import.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseImportComponent {
  @Output() fileSelected = new EventEmitter<File>();

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onFilesDropped(files: FileList): void {
    this.emitFirst(files);
  }

  public onInputChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.emitFirst(input.files);
    // Reset so selecting the same file again still triggers a change event.
    input.value = '';
  }

  public onOpen(trigger: HTMLInputElement): void {
    trigger.click();
  }

  public onBrowse(event: Event, trigger: HTMLInputElement): void {
    // Stop the click bubbling to the drop zone so the dialog only opens once.
    event.stopPropagation();
    trigger.click();
  }

  public onKeydown(event: KeyboardEvent, trigger: HTMLInputElement): void {
    event.preventDefault();
    trigger.click();
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private emitFirst(files: FileList | null): void {
    const file = files?.item(0);

    if (file) {
      this.fileSelected.emit(file);
    }
  }
}
