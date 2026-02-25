import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

@Injectable({
    providedIn: 'root'
  })
export class LoaderService {
  private loadingCounter = 0;
  private isLoadingSubject = new BehaviorSubject<boolean>(false);
  public isLoading$: Observable<boolean> = this.isLoadingSubject.asObservable();
  private showTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private readonly showDelayMs = 1000;


  show(): void {
    this.loadingCounter++;
    if (this.loadingCounter === 1) {
      if (this.showTimeoutId) {
        clearTimeout(this.showTimeoutId);
      }
      this.showTimeoutId = setTimeout(() => {
        this.showTimeoutId = null;
        if (this.loadingCounter > 0) {
          this.isLoadingSubject.next(true);
        }
      }, this.showDelayMs);
    }
  }

  
  hide(): void {
    this.loadingCounter = Math.max(0, this.loadingCounter - 1);
    if (this.loadingCounter === 0) {
      if (this.showTimeoutId) {
        clearTimeout(this.showTimeoutId);
        this.showTimeoutId = null;
      }
      this.isLoadingSubject.next(false);
    }
  }
}