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

import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiCallService } from '../../../services/api-call.service';
import { StartAssistantDecision, StartAssistantOffer } from '../models/onboarding-assistant.model';
import { BestPracticeModelCard, BestPracticeModelDetails } from '../models/onboarding-best-practice.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable({
    providedIn: 'root'
})
export class OnboardingWorkspaceService {
    private readonly api = inject(ApiCallService);

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public getOffer(): Observable<StartAssistantOffer> {
        return this.api.callGet<StartAssistantOffer>('start_assistant/offer').pipe(
            map(response => response.body)
        );
    }


    /** Refused with a 400 once the installation is no longer empty. */
    public recordDecision(decision: StartAssistantDecision) {
        return this.api.callPost<void>('start_assistant/decision', { decision });
    }


    /** Needs the right `base.*`; `confirm` must be the typed `RESET`. */
    public resetConfiguration(confirm: string) {
        return this.api.callPost<void>('configuration_transfer/reset', { confirm });
    }


    public getBestPracticeModels(): Observable<BestPracticeModelCard[]> {
        return this.api.callGet<BestPracticeModelCard[]>('start_assistant/models').pipe(
            map(response => response.body ?? [])
        );
    }


    public getBestPracticeModel(modelId: string): Observable<BestPracticeModelDetails> {
        return this.api.callGet<BestPracticeModelDetails>(`start_assistant/models/${encodeURIComponent(modelId)}`).pipe(
            map(response => response.body)
        );
    }


    /** Needs the right `base.*`, on an empty installation. */
    public applyBestPracticeModel(modelId: string) {
        return this.api.callPost<void>(`start_assistant/models/${encodeURIComponent(modelId)}`, null);
    }
}
