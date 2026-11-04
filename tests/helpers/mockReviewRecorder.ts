import type {Page} from '@playwright/test';

export async function mockReviewRecorder(page: Page, wav: number[]) {
  await page.addInitScript((bytes) => {
    const state: any = { calls: 0, stopped: 0, starts: 0, types: [], denied: false, oversize: false, pending: false };
    (window as any).__voice = state;
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async () => {
      state.calls++;
      if (state.denied) throw new DOMException('Denied', 'NotAllowedError');
      const stream = { getTracks: () => [{ stop() { state.stopped++; } }] };
      if (state.pending) return new Promise(resolve => { state.resolve = () => resolve(stream); });
      return stream;
    }});
    class Recorder {
      static isTypeSupported(type: string) { state.types.push(type); return type.startsWith('audio/mp4'); }
      state = 'inactive'; mimeType: string; ondataavailable: any; onstop: any;
      constructor(_stream: any, options: any) { this.mimeType = options.mimeType; state.mime = this.mimeType; }
      start() { this.state='recording'; state.starts++; }
      stop() {
        this.state='inactive';
        setTimeout(() => {
          const data = state.oversize ? new Uint8Array(5*1024*1024+1) : new Uint8Array(bytes);
          this.ondataavailable?.({data: new Blob([data], {type: this.mimeType})});
          this.onstop?.();
        }, 0);
      }
    }
    (window as any).MediaRecorder = Recorder;
  }, wav);
}
