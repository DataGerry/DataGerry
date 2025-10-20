
import { Component, OnInit, OnDestroy, ViewChild, ElementRef, Input } from '@angular/core';

@Component({
  selector: 'app-voice-wave-visualizer',
  template: `
    <div class="voice-waves">
      <canvas #waveCanvas class="wave-canvas"></canvas>
    </div>
  `,
  styles: [`
    .voice-waves {
      position: relative;
      width: 200px;
      height: 50px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      flex-shrink: 0;
    }

    .wave-canvas {
      width: 100%;
      height: 100%;
    }
  `]
})
export class VoiceWaveVisualizerComponent implements OnInit, OnDestroy {
  @ViewChild('waveCanvas', { static: true }) canvasRef!: ElementRef<HTMLCanvasElement>;
  @Input() isActive = false;

  private canvas!: HTMLCanvasElement;
  private ctx!: CanvasRenderingContext2D;
  private animationId?: number;
  private audioContext?: AudioContext;
  private analyser?: AnalyserNode;
  private dataArray?: Uint8Array;
  private bufferLength?: number;

  ngOnInit(): void {
    this.canvas = this.canvasRef.nativeElement;
    this.ctx = this.canvas.getContext('2d')!;
    
    // Set canvas size
    this.canvas.width = 200;
    this.canvas.height = 50;
    
    this.startVisualization();
  }

  ngOnDestroy(): void {
    this.stopVisualization();
  }

  async startVisualization(): Promise<void> {
    try {
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      // Create audio context
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      
      const source = this.audioContext.createMediaStreamSource(stream);
      source.connect(this.analyser);
      
      this.bufferLength = this.analyser.frequencyBinCount;
      this.dataArray = new Uint8Array(this.bufferLength);
      
      this.draw();
    } catch (error) {
      console.error('Error accessing microphone:', error);
      // Fallback to animated waves if mic access fails
      this.drawAnimatedWaves();
    }
  }

  private draw = (): void => {
    if (!this.isActive) {
      this.drawAnimatedWaves();
      return;
    }

    this.animationId = requestAnimationFrame(this.draw);

    if (this.analyser && this.dataArray) {
      this.analyser.getByteFrequencyData(this.dataArray);
    }

    // Clear canvas
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    
    // Draw multiple wave layers
    this.drawWaveLayer(this.dataArray || new Uint8Array(64), '#dc3545', 3, 0);
    this.drawWaveLayer(this.dataArray || new Uint8Array(64), 'rgba(220, 53, 69, 0.6)', 2, 0.3);
    this.drawWaveLayer(this.dataArray || new Uint8Array(64), 'rgba(220, 53, 69, 0.4)', 2, 0.6);
  };

  private drawWaveLayer(data: Uint8Array, color: string, lineWidth: number, offset: number): void {
    this.ctx.beginPath();
    this.ctx.strokeStyle = color;
    this.ctx.lineWidth = lineWidth;
    this.ctx.lineCap = 'round';
    this.ctx.lineJoin = 'round';

    const sliceWidth = this.canvas.width / data.length;
    let x = 0;

    for (let i = 0; i < data.length; i++) {
      const v = data[i] / 255.0; // Normalize to 0-1
      const y = (v * this.canvas.height / 2) + (this.canvas.height / 2);

      if (i === 0) {
        this.ctx.moveTo(x, y + (offset * 5));
      } else {
        this.ctx.lineTo(x, y + (offset * 5));
      }

      x += sliceWidth;
    }

    this.ctx.stroke();
  }

  private drawAnimatedWaves(): void {
    this.animationId = requestAnimationFrame(() => this.drawAnimatedWaves());
    
    const time = Date.now() * 0.002;
    
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    
    // Draw three sine waves with different frequencies
    this.drawSineWave(time, '#dc3545', 3, 1, 0);
    this.drawSineWave(time + 0.3, 'rgba(220, 53, 69, 0.6)', 2, 1.5, 5);
    this.drawSineWave(time + 0.6, 'rgba(220, 53, 69, 0.4)', 2, 2, 10);
  }

  private drawSineWave(time: number, color: string, lineWidth: number, frequency: number, yOffset: number): void {
    this.ctx.beginPath();
    this.ctx.strokeStyle = color;
    this.ctx.lineWidth = lineWidth;
    this.ctx.lineCap = 'round';

    for (let x = 0; x < this.canvas.width; x++) {
      const y = this.canvas.height / 2 + 
                Math.sin(x * 0.05 * frequency + time) * 15 * Math.sin(time * 2) +
                yOffset;
      
      if (x === 0) {
        this.ctx.moveTo(x, y);
      } else {
        this.ctx.lineTo(x, y);
      }
    }

    this.ctx.stroke();
  }

  stopVisualization(): void {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
    
    if (this.audioContext) {
      this.audioContext.close();
    }
  }
}