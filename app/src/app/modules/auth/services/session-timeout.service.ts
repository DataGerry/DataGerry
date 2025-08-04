/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { Injectable, OnDestroy } from '@angular/core';

import { interval, Observable, ReplaySubject, Subject, Subscription } from 'rxjs';

import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { AuthService } from './auth.service';
import { ToastService } from '../../../layout/toast/toast.service';

import { Token } from '../models/token';
import { SessionTimeoutModalComponent } from '../modals/session-timeout-modal/session-timeout-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */
@Injectable({
  providedIn: 'root'
})
export class SessionTimeoutService implements OnDestroy {

  /**
   * In which ms interval should the session be checked.
   * Default is every 1 second.
   */
  static readonly TIME_CHECK_INTERVAL: number = 1000;

  /**
   * Which time distance should the notification modal appear.
   * Default is 15 minutes before the timeout.
   */
  static readonly NOTIFICATION_THRESHOLD: number = 1000 * 60 * 15;

  /**
   * Component un-subscriber.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * Notification modal reference.
   * @private
   */
  private notificationModalRef: NgbModalRef;

  /**
   * Trigger if the notification modal was already triggered.
   * @private
   */
  private notified: boolean = false;

  /**
   * Interval trigger.
   * @private
   */
  private intervalTimer$: Observable<number> = interval(SessionTimeoutService.TIME_CHECK_INTERVAL);

  /**
   * Interval subscription.
   * @private
   */
  private timerSubscription = new Subscription();

  /**
   * Timeout time emitter.
   */
  public sessionTimeout: Subject<number>;

  /**
   * Same as timeout emitter but human readable.
   */
  public sessionTimeoutRemaining: Subject<string>;

  /**
   * POSIX timestamp * 1000 of the token lifetime rest.
   * @private
   */
  private tokenExpire: number;

  constructor(private authService: AuthService, private modal: NgbModal, private toast: ToastService) {
    this.sessionTimeout = new Subject<number>();
    this.sessionTimeoutRemaining = new Subject<string>();
    this.authService.currentUserToken.subscribe((token: Token) => {
      if (token) {
        this.tokenExpire = token.expire * 1000;
        this.startTimer();
      } else {
        this.stopTimer();
      }
    });

  }

  /**
   * Converts a posix timestamp in ms to a countdown format
   * @param msecs
   */
  public static convertToCountdown(msecs) {
    const secsInt = Math.floor(parseInt(msecs, 10) / 1000);
    const days = Math.floor(secsInt / 86400) % 7;
    const hours = Math.floor(secsInt / 3600) % 24;
    const minutes = Math.floor(secsInt / 60) % 60;
    const seconds = secsInt % 60;
    return [days, hours, minutes, seconds]
      .map(v => v < 10 ? '0' + v : v)
      .filter((v, i) => v !== '00' || i > 0)
      .join(':');
  }

  /**
   * Remaining token lifetime.
   */
  public get remaining(): number {
    if (!this.tokenExpire) {
      return 0;
    }
    const currentTime: number = Date.now();
    const distance = this.tokenExpire - currentTime;

    if (distance > 0) {
      return distance;
    }
    return 0;
  }

  /**
   * Starts the timer.
   * @private
   */
  private startTimer(): void {
    if (this.timerSubscription) {
      this.stopTimer();
    }
    if (!this.intervalTimer$) {
      this.intervalTimer$ = interval(SessionTimeoutService.TIME_CHECK_INTERVAL);
    }
    this.notified = false;
    this.timerSubscription = this.intervalTimer$.subscribe((t: number) => {
      this.sessionTimeout.next(this.remaining);
      this.sessionTimeoutRemaining.next(SessionTimeoutService.convertToCountdown(this.remaining));
      if (this.remaining <= 0) {
        this.cleanUpTimer();
        this.authService.logout();
      } else if ((this.remaining <= SessionTimeoutService.NOTIFICATION_THRESHOLD) && !this.notified) {
        this.notified = true;
        this.notifyPossibleTimeout();
      }
    });
  }

  /**
   * Shows the notification modal and renews the session if password was passed.
   * @private
   */
  private notifyPossibleTimeout() {
    this.notificationModalRef = this.modal.open(SessionTimeoutModalComponent);
    this.notificationModalRef.componentInstance.remainingTime$ = this.sessionTimeoutRemaining;
    this.notificationModalRef.result.then(
      (result) => {
        if (result.renewed) {
          this.toast.success('Session renewed!');
        } else {
          this.displayLogoutWarning();
        }
      },
      () => {
        this.displayLogoutWarning();
      }
    );
  }

  /**
   * Display a warning toast with rest time before logout.
   * @private
   */
  private displayLogoutWarning(): void {
    const logoutTime: Date = new Date(this.tokenExpire);
    this.toast.warning(`You will be logged out at ${ logoutTime }`);
  }

  /**
   * Stops the timer subscription.
   * @private
   */
  private stopTimer(): void {
    this.timerSubscription.unsubscribe();
  }

  /**
   * Kills all timers.
   * @private
   */
  private cleanUpTimer(): void {
    this.sessionTimeout.complete();
    this.sessionTimeoutRemaining.complete();
    this.stopTimer();
    if (this.notificationModalRef) {
      this.notificationModalRef.close();
    }
  }

  public ngOnDestroy(): void {
    this.cleanUpTimer();
    this.subscriber?.next();
    this.subscriber?.complete();
  }
}
