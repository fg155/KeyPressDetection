/* Monotonic display clock; backend snapshots remain authoritative on completion. */
(function (root) {
  'use strict';
  class ElapsedClock {
    constructor(now = () => performance.now()) { this.now = now; this.reset(); }
    reset() { this.id = null; this.base = 0; this.at = this.now(); this.live = false; }
    value() { return this.base + (this.live ? Math.max(0, this.now() - this.at) / 1000 : 0); }
    sync(job) {
      const live = ['running', 'stopping'].includes(job.status);
      const elapsed = Number.isFinite(job.elapsed) ? Math.max(0, job.elapsed) : 0;
      this.base = live && this.id === job.id ? Math.max(elapsed, this.value()) : elapsed;
      this.id = job.id; this.at = this.now(); this.live = live;
    }
    pause() { this.base = this.value(); this.at = this.now(); this.live = false; }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = ElapsedClock;
  else root.ElapsedClock = ElapsedClock;
})(typeof window === 'undefined' ? globalThis : window);
