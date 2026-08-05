import { Injectable } from '@angular/core';
import { Notification, NotificationType } from './notification.model';
import { NotificationQuery } from './notification.query';
import { NotificationStore } from './notification.store';

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly storageKey = 'cmdb.notifications';

  constructor(
    private readonly notificationStore: NotificationStore,
    private readonly notificationQuery: NotificationQuery
  ) {
    this.restoreFromStorage();
  }

  public add(message: string, type: NotificationType): void {
    const normalizedMessage = (message ?? '').trim();
    if (!normalizedMessage) {
      return;
    }

    const notification: Notification = {
      id: this.createId(),
      message: normalizedMessage,
      type,
      timestamp: new Date().toISOString()
    };

    this.notificationStore.add(notification);
    this.persist();
  }

  public clear(): void {
    this.notificationStore.set([]);
    this.persist();
  }

  private restoreFromStorage(): void {
    const rawValue = this.safeGetFromStorage();
    if (!rawValue) {
      return;
    }

    try {
      const parsedValue = JSON.parse(rawValue);
      if (!Array.isArray(parsedValue)) {
        return;
      }

      const notifications = parsedValue
        .filter(this.isNotificationLike)
        .map(item => ({
          id: item.id,
          message: item.message.trim(),
          type: item.type,
          timestamp: item.timestamp
        }))
        .filter(item => item.message.length > 0);

      this.notificationStore.set(notifications);
    } catch {
      this.notificationStore.set([]);
    }
  }

  private safeGetFromStorage(): string | null {
    try {
      return localStorage.getItem(this.storageKey);
    } catch {
      return null;
    }
  }

  private persist(): void {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify(this.notificationQuery.getAll()));
    } catch {
      // localStorage can fail in private mode or restricted browser contexts
    }
  }

  private createId(): string {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
      return crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  private isNotificationLike = (value: unknown): value is Notification => {
    const candidate = value as Notification;
    return !!candidate &&
      typeof candidate.id === 'string' &&
      typeof candidate.message === 'string' &&
      this.isNotificationType(candidate.type) &&
      typeof candidate.timestamp === 'string';
  };

  private isNotificationType(value: string): value is NotificationType {
    return value === 'success' || value === 'error' || value === 'info' || value === 'warning';
  }
}
