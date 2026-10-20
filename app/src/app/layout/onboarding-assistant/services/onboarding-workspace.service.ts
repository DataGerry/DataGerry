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

import { Injectable, inject } from '@angular/core';

import { ApiCallService } from '../../../services/api-call.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
    providedIn: 'root'
})
export class OnboardingWorkspaceService {
    private readonly api = inject(ApiCallService);

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Admin account (public_id 1) only; `confirm` must be the typed `RESET`. */
    public resetConfiguration(confirm: string) {
        return this.api.callPost<void>('configuration_transfer/reset', { confirm });
    }
}
