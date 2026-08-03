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
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
/* ------------------------------------------------------------------------------------------------------------------ */


@Component({
    selector: 'dg-modal',
    standalone: true,
    templateUrl: './dg-modal.component.html',
    styleUrls: ['./dg-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class DgModalComponent {

    /** Font Awesome class for the header icon chip; omit to hide the chip. */
    public readonly icon = input<string>();
    /** Small uppercase label above the title. */
    public readonly eyebrow = input<string>();
    public readonly title = input('');
    public readonly subtitle = input<string>();
    /** When false the body is a flex column that clips overflow, letting a child own the scroll. */
    public readonly scrollBody = input(true);

    /** Emitted when the header close button is pressed; the host decides how to dismiss. */
    public readonly dismiss = output<void>();
}
