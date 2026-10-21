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
import { Directive, TemplateRef, inject, input } from '@angular/core';

/**
 * Contributes one host-owned tab to the object-relations strip, so the panel
 * itself stays free of any knowledge about what the tab shows:
 *
 * ```html
 * <ng-template cmdbObjectTab="rack-view" label="Rack View" icon="fas fa-server">
 *   <cmdb-rack-overview [publicId]="objectId"></cmdb-rack-overview>
 * </ng-template>
 * ```
 */
@Directive({
  selector: 'ng-template[cmdbObjectTab]',
  standalone: false
})
export class ObjectTabDirective {

  /* --------------------------------------------------- INPUTS --------------------------------------------------- */

  /** Identifies the tab in the strip; must be unique among the host's tabs. */
  public readonly key = input.required<string>({ alias: 'cmdbObjectTab' });
  public readonly label = input.required<string>();
  public readonly icon = input('');

  public readonly template = inject(TemplateRef<unknown>);
}
