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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, OnDestroy, inject } from '@angular/core';

import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { RenderFieldComponent } from '../components.fields';
import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { ExtendableOptionManagerService } from 'src/app/core/services/extendable-option-manager.service';
import { ManageableOptionType } from 'src/app/core/components/extendable_option_manager/manageable-option-types';

@Component({
    templateUrl: './select.component.html',
    styleUrls: ['./select.component.scss'],
    standalone: false
})
export class SelectComponent extends RenderFieldComponent implements OnDestroy {

  private readonly optionManager = inject(ExtendableOptionManagerService);
  private readonly optionCatalog = inject(ExtendableOptionCatalogService);
  private readonly subscriber = new ReplaySubject<void>();

  public constructor() {
    super();
  }


  public ngOnDestroy(): void {
    this.subscriber.next();
    this.subscriber.complete();
  }


  /** Set only for a select whose options a user may extend, e.g. the port selects. */
  public get manageableOption(): ManageableOptionType | null {
    return this.optionManager.descriptorOf(this.data?.option_type);
  }


  /** Reads the refreshed list straight back into the dropdown. */
  public openOptionManager(): void {
    this.optionManager.open(this.data?.option_type)
      .pipe(takeUntil(this.subscriber))
      .subscribe(() => this.reloadOptions());
  }


  private reloadOptions(): void {
    this.optionCatalog.optionsFor(this.data?.option_type)
      .pipe(takeUntil(this.subscriber))
      .subscribe((options) => { this.data.options = options; });
  }
}
