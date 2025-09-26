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
import { Injectable } from '@angular/core';
import { Observable, Subject } from 'rxjs';

export interface SpeechRecognitionResult {
  transcript: string;
  isFinal: boolean;
  confidence: number;
}

export interface SpeechRecognitionError {
  error: string;
  message: string;
}

@Injectable({
  providedIn: 'root'
})
export class SpeechRecognitionService {
  private recognition: any;
  private transcriptSubject = new Subject<SpeechRecognitionResult>();
  private errorSubject = new Subject<SpeechRecognitionError>();
  private statusSubject = new Subject<string>();
  private isRecording = false;

  constructor() {
    this.initializeRecognition();
  }

  private initializeRecognition(): void {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    
    if (!SpeechRecognition) {
      this.errorSubject.next({
        error: 'NOT_SUPPORTED',
        message: 'Speech recognition is not supported in this browser.'
      });
      return;
    }

    this.recognition = new SpeechRecognition();
    this.recognition.continuous = false;
    this.recognition.interimResults = true;
    this.recognition.lang = 'en-US';
    this.recognition.maxAlternatives = 1;

    this.recognition.onstart = () => {
      this.isRecording = true;
      this.statusSubject.next('recording');
    };

    this.recognition.onresult = (event: any) => {
      let finalTranscript = '';
      let interimTranscript = '';

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interimTranscript += transcript;
        }
      }

      if (interimTranscript) {
        this.transcriptSubject.next({
          transcript: interimTranscript,
          isFinal: false,
          confidence: event.results[event.results.length - 1][0].confidence
        });
      }

      if (finalTranscript) {
        this.transcriptSubject.next({
          transcript: finalTranscript,
          isFinal: true,
          confidence: event.results[event.results.length - 1][0].confidence
        });
      }
    };

    this.recognition.onerror = (event: any) => {
      this.isRecording = false;
      this.statusSubject.next('error');
      
      let errorMessage = 'An unknown error occurred';
      switch (event.error) {
        case 'no-speech':
          errorMessage = 'No speech was detected. Please try again.';
          break;
        case 'audio-capture':
          errorMessage = 'No microphone was found. Please ensure a microphone is connected.';
          break;
        case 'not-allowed':
          errorMessage = 'Permission to use microphone is blocked. Please allow microphone access.';
          break;
        case 'network':
          errorMessage = 'Network error occurred during speech recognition.';
          break;
        default:
          errorMessage = `Speech recognition error: ${event.error}`;
      }

      this.errorSubject.next({
        error: event.error,
        message: errorMessage
      });
    };

    this.recognition.onend = () => {
      this.isRecording = false;
      this.statusSubject.next('stopped');
    };
  }

  startListening(): void {
    if (!this.recognition) {
      this.errorSubject.next({
        error: 'NOT_INITIALIZED',
        message: 'Speech recognition is not available in this browser.'
      });
      return;
    }

    if (this.isRecording) {
      this.stopListening();
    }

    try {
      this.recognition.start();
    } catch (error) {
      this.errorSubject.next({
        error: 'START_FAILED',
        message: 'Failed to start speech recognition. Please try again.'
      });
    }
  }

  stopListening(): void {
    if (this.recognition && this.isRecording) {
      try {
        this.recognition.stop();
      } catch (error) {
        // Ignore errors when stopping
      }
    }
  }

  getTranscript(): Observable<SpeechRecognitionResult> {
    return this.transcriptSubject.asObservable();
  }

  getErrors(): Observable<SpeechRecognitionError> {
    return this.errorSubject.asObservable();
  }

  getStatus(): Observable<string> {
    return this.statusSubject.asObservable();
  }

  isRecordingActive(): boolean {
    return this.isRecording;
  }

  setLanguage(language: string): void {
    if (this.recognition) {
      this.recognition.lang = language;
    }
  }
}
