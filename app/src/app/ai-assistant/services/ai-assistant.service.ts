import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { AiAssistantMessage } from '../models/ai-suggestion.model';
import { TypeSelectionPayload } from '../models/ai-type-selection.models';
import { TypeAssistantResponse } from '../models/ai-assistant-response.model';

@Injectable({ providedIn: 'root' })
export class AiAssistantService extends BaseApiService<any> {
  public servicePrefix = 'ai/type_assistant/message';

  constructor(protected api: ApiCallService) { super(api); }

  /** Send prompt - backend returns { data, is_valid_type } */
  postMessage(message: AiAssistantMessage): Observable<TypeAssistantResponse<any>> {
    return this.handlePostRequest<TypeAssistantResponse<any>>(`${this.servicePrefix}`, message);
  }

  /** submit the final selection for persistence/next step */
  submitSelection(payload: TypeSelectionPayload): Observable<any> {
    return this.handlePostRequest<any>(`ai/type_assistant/selection`, payload);
  }
}
