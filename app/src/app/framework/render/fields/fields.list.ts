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
import { TextComponent } from './text/text.component';
import { PasswordComponent } from './text/password.component';
import { TextareaComponent } from './textarea/textarea.component';
import { CheckboxComponent } from './choice/checkbox.component';
import { RadioComponent } from './choice/radio.component';
import { SelectComponent } from './choice/select.component';
import { RefComponent } from './special/ref.component';
import { LocationComponent } from './special/location.component';
import { DateComponent } from './date/date.component';
import { NumberComponent } from './math/number.component';
import { RefSectionComponent } from './section/ref-section.component';
/* ------------------------------------------------------------------------------------------------------------------ */

export const fieldComponents: { [type: string]: any } = {
    'text': TextComponent,
    'password': PasswordComponent,
    'textarea': TextareaComponent,
    'number': NumberComponent,
    'checkbox': CheckboxComponent,
    'radio': RadioComponent,
    'select': SelectComponent,
    'ref': RefComponent,
    'location': LocationComponent,
    'date': DateComponent,
    'ref-section-field': RefSectionComponent
};
