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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { HttpParams } from '@angular/common/http';

import { ApiCallService } from 'src/app/services/api-call.service';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { RunFlowchart, OcTrace, OcTraceSegment } from '../models/automation-run-log.model';

@Injectable({ providedIn: 'root' })
export class AutomationsService extends BaseApiService<any> {
  public servicePrefix = 'open_celium';

  constructor(protected api: ApiCallService) {
    super(api);
  }

  getOpenCeliumConfigStatus(): Observable<OpenCeliumConfigStatus> {
    return this.handleGetRequest<OpenCeliumConfigStatus>('config_file/status/opencelium', new HttpParams());
  }

  // LIST
  getAutomations(): Observable<any[]> {
    const params = new HttpParams();
    return this.handleGetRequest<any[]>(`${this.servicePrefix}/schedulers`, params);
  }

  // GET TEMPLATES BY CONNECTORS
  getTemplatesByConnectors(fromConnectorId: number, toConnectorId: number): Observable<any[]> {
    const params = new HttpParams();
    return this.handleGetRequest<any[]>(`${this.servicePrefix}/templates/all/${fromConnectorId}/${toConnectorId}`, params);
  }

  // GET SCHEDULER - carries lastExecution, whose durations say how long a run usually takes
  getScheduler(schedulerId: number): Observable<any> {
    return this.handleGetRequest<any>(`${this.servicePrefix}/schedulers/${schedulerId}`, new HttpParams());
  }

  // GET CONNECTION
  getConnection(connectionId: number): Observable<any> {
    const params = new HttpParams();
    return this.handleGetRequest<any>(`${this.servicePrefix}/connections/${connectionId}`, params);
  }

  // CREATE
  createAutomation(payload: any): Observable<any> {
    return this.handlePostRequest<any>(`${this.servicePrefix}/schedulers`, payload);
  }

  // UPDATE
  updateConnection(connectionId: number, payload: any): Observable<any> {
    const body: any = { ...payload, connectionId };
    return this.handlePutRequest<any>(`${this.servicePrefix}/connections/${connectionId}`, body);
  }

  updateScheduler(schedulerId: number, payload: any): Observable<any> {
    const body: any = { ...payload, schedulerId };
    return this.handlePutRequest<any>(`${this.servicePrefix}/schedulers/${schedulerId}`, body);
  }

  // DELETE
  deleteAutomation(automationId: number) {
    return this.handleDeleteRequest<void>(`${this.servicePrefix}/schedulers/${automationId}`);
  }

  // EXECUTE SCHEDULER
  executeScheduler(automationId: number){
    return this.handleGetRequest<void>(`${this.servicePrefix}/schedulers/execute/${automationId}`, new HttpParams());
  }

  // GET RUNNING SCHEDULERS
  getRunningSchedulers(): Observable<any[]> {
    return this.handleGetRequest<any[]>(`${this.servicePrefix}/schedulers/running`, new HttpParams());
  }

  // GET SCHEDULER LOGS
  getSchedulerLogs(schedulerId: number, status: 's' | 'f'): Observable<any[]> {
    const params = new HttpParams()
      .set('scheduler_id', `${schedulerId}`)
      .set('status', status);
    return this.handleGetRequest<any[]>(`${this.servicePrefix}/schedulers/logs`, params);
  }

  /* ----------------------------------------------- RUN LOG - ROUTES ----------------------------------------------- */

  /**
   * The connector branches of one run.
   *
   * A run splits into one branch per connector, and each branch is fetched separately - this call
   * only names them. `id` is what the first level is asked for, `flowId` is what everything below
   * addresses itself by.
   */
  getRunFlowcharts(executionId: number): Observable<RunFlowchart[]> {
    return this.handleGetRequest<RunFlowchart[]>(
      `${this.servicePrefix}/connections/logs/flowcharts/${executionId}`,
      new HttpParams()
    );
  }


  /** The steps a branch ran at its top level. What runs inside a loop or a branch is not in here. */
  getRunFirstLevel(flowchartId: string | number): Observable<OcTrace[]> {
    return this.handleGetRequest<OcTrace[]>(
      `${this.servicePrefix}/connections/logs/first_level/${flowchartId}`,
      new HttpParams()
    );
  }


  /**
   * The detail of one step: request and response for a call, the verdict for a condition.
   *
   * Not part of the tree - it weighs too much to send for every step, so it is asked for when a
   * line is opened.
   */
  getRunStepDetails(stepId: string): Observable<{ segment?: OcTraceSegment }> {
    return this.handleGetRequest<{ segment?: OcTraceSegment }>(
      `${this.servicePrefix}/connections/logs/${stepId}`,
      new HttpParams()
    );
  }


  /**
   * What ran inside a condition or a loop.
   *
   * `loopIndex` is the entry of the innermost enclosing loop, and the route requires it - a step
   * outside any loop passes 0. OpenCelium returns the children of that one entry, which is why
   * walking a loop costs one call per entry.
   */
  getRunStepChildren(stepId: string, loopIndex: number): Observable<OcTrace[]> {
    const params = new HttpParams().set('loopIndex', `${loopIndex}`);

    return this.handleGetRequest<OcTrace[]>(
      `${this.servicePrefix}/connections/logs/children/${stepId}`,
      params
    );
  }


  /** Throws away everything a run wrote. */
  deleteRunLogs(executionId: number): Observable<void> {
    return this.handleDeleteRequest<void>(`${this.servicePrefix}/connections/logs/${executionId}`);
  }
}

export type OpenCeliumConfigStatus = {
  status: boolean;
  section: boolean;
  host: boolean;
  port: boolean;
  protocol: boolean;
  email: boolean;
  user: boolean;
  password: boolean;
};
