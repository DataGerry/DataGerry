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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ControlsCommon } from './controls.common';
import { TextControl } from './text/text.control';
import { PasswordControl } from './text/password.control';
import { TextAreaControl } from './text/textarea.control';
import { NumberControl } from './number/number.control';
import { CheckboxControl } from './choice/checkbox.control';
import { RadioControl } from './choice/radio.control';
import { SelectControl } from './choice/select.control';
import { DateControl } from './date-time/date.control';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The basic control set, identical for the type, relation and section template builders.
 * Order is significant - it is the order the palette renders.
 */
export const BASIC_CONTROLS: ReadonlyArray<ControlsCommon> = Object.freeze([
    new TextControl(),
    new NumberControl(),
    new PasswordControl(),
    new TextAreaControl(),
    new CheckboxControl(),
    new RadioControl(),
    new SelectControl(),
    new DateControl()
]);
