// Each browser owns its cache. Two stable viewer keys cover the current quiz;
// a new question's generation discards the previous question's transforms.
const views = new Map();

export default {
  template: `
    <div class="flex flex-col w-full h-full min-h-0" :aria-label="label + ' viewer'">
      <div class="flex items-center justify-end gap-1 text-tt-main" style="flex:none">
        <q-btn flat dense icon="remove" :aria-label="'Zoom out: ' + label" :disable="status !== 'loaded' || zoom <= 1" @click="setZoom(zoom / 1.5)" />
        <span class="text-xs" style="min-width:3em;text-align:center">{{ Math.round(zoom * 100) }}%</span>
        <q-btn flat dense icon="add" :aria-label="'Zoom in: ' + label" :disable="status !== 'loaded' || zoom >= 12" @click="setZoom(zoom * 1.5)" />
        <q-btn flat dense label="Fit" :aria-label="'Fit photo: ' + label" :disable="status !== 'loaded'" @click="fit" />
      </div>
      <div ref="frame" class="relative flex items-center justify-center w-full flex-1 min-h-0 overflow-hidden"
           :aria-label="label" role="region" tabindex="0"
           :style="{touchAction:'none', cursor: zoom > 1 ? (dragging ? 'grabbing' : 'grab') : 'default'}"
           @wheel.prevent="wheel" @dblclick.prevent="setZoom(zoom > 1 ? 1 : 2, $event)"
           @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp"
           @pointercancel="pointerUp" @keydown="key">
        <img :key="source + ':' + retry" ref="image" :src="source" :alt="label" draggable="false"
             @load="loaded" @error="failed"
             :style="{position:'absolute', left:width ? '50%' : '0', top:height ? '50%' : '0', marginLeft:-width/2+'px', marginTop:-height/2+'px', width:width ? width+'px' : '100%', height:height ? height+'px' : '100%', objectFit:'scale-down', maxWidth:'none', maxHeight:'none', flexShrink:0,
                      visibility:status === 'error' ? 'hidden' : 'visible',
                      transform:'translate('+x+'px,'+y+'px) scale('+zoom+')', userSelect:'none'}" />
        <div v-if="status === 'loading'" role="status" class="absolute bottom-2 bg-tt-surface rounded px-2 py-1 text-tt-muted text-sm">Loading photo…</div>
        <div v-if="status === 'error'" role="alert" class="absolute flex flex-col items-center gap-2 text-tt-main p-3">
          <span>This photo couldn’t be loaded.</span>
          <div class="flex gap-2">
            <q-btn flat dense label="Retry" color="primary" @click.stop="tryAgain" />
            <q-btn v-if="has_next" flat dense label="Try another photo" color="primary" @click.stop="$emit('next')" />
          </div>
        </div>
      </div>
    </div>`,
  props: { source: String, cache_key: String, generation: Number, label: String, has_next: Boolean },
  emits: ['next'],
  data() {
    const saved = views.get(this.cache_key);
    if (!saved || saved.generation !== this.generation) {
      views.set(this.cache_key, {generation: this.generation, photos: new Map()});
    }
    const transform = views.get(this.cache_key).photos.get(this.source) || {zoom:1,x:0,y:0};
    return {...transform, width:0, height:0, status:'loading', retry:0, dragging:false};
  },
  mounted() {
    this.pointers = new Map();
    this.observer = new ResizeObserver(() => {
      cancelAnimationFrame(this.resizeFrame);
      this.resizeFrame = requestAnimationFrame(() => this.resize());
    });
    this.observer.observe(this.$refs.frame);
    if (this.$refs.image.complete && this.$refs.image.naturalWidth) this.loaded({target:this.$refs.image});
  },
  beforeUnmount() { this.save(); this.observer.disconnect(); cancelAnimationFrame(this.resizeFrame); },
  methods: {
    save() { const cache=views.get(this.cache_key); if (cache?.generation === this.generation) cache.photos.set(this.source, {zoom:this.zoom,x:this.x,y:this.y}); },
    resize() {
      const image = this.$refs.image, frame = this.$refs.frame;
      if (!image?.naturalWidth || !frame?.clientWidth || !frame?.clientHeight) return;
      const scale = Math.min(frame.clientWidth / image.naturalWidth, frame.clientHeight / image.naturalHeight, 1);
      this.width = image.naturalWidth * scale;
      this.height = image.naturalHeight * scale;
      this.clamp();
    },
    clamp() {
      const frame = this.$refs.frame;
      if (!frame) return;
      const maxX = Math.max(0, (this.width * this.zoom - frame.clientWidth) / 2);
      const maxY = Math.max(0, (this.height * this.zoom - frame.clientHeight) / 2);
      this.x = Math.max(-maxX, Math.min(maxX, this.x));
      this.y = Math.max(-maxY, Math.min(maxY, this.y));
      this.save();
    },
    loaded(event) { if (event.target !== this.$refs.image) return; this.status='loaded'; this.resize(); },
    failed(event) { if (event.target === this.$refs.image) this.status='error'; },
    tryAgain() { this.status='loading'; this.retry++; },
    fit() { this.zoom=1; this.x=0; this.y=0; this.save(); },
    setZoom(value, event) {
      if (this.status !== 'loaded') return;
      const next = Math.max(1, Math.min(12, value));
      if (event) {
        const box = this.$refs.frame.getBoundingClientRect();
        const px = event.clientX - box.left - box.width / 2;
        const py = event.clientY - box.top - box.height / 2;
        this.x = px - (px - this.x) * next / this.zoom;
        this.y = py - (py - this.y) * next / this.zoom;
      }
      this.zoom = next;
      this.clamp();
    },
    wheel(event) { this.setZoom(this.zoom * Math.exp(-event.deltaY * 0.002), event); },
    pointerDown(event) {
      if (event.target.closest('button')) return;
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      this.$refs.frame.setPointerCapture(event.pointerId);
      this.pointers.set(event.pointerId, {x:event.clientX,y:event.clientY});
      this.dragging = true;
    },
    pointerMove(event) {
      const previous = this.pointers.get(event.pointerId);
      if (!previous) return;
      const oldPoints = [...this.pointers.values()];
      this.pointers.set(event.pointerId, {x:event.clientX,y:event.clientY});
      const points = [...this.pointers.values()];
      if (points.length === 2) {
        const distance = list => Math.hypot(list[0].x-list[1].x,list[0].y-list[1].y);
        const oldDistance = distance(oldPoints);
        if (oldDistance > 0) this.setZoom(this.zoom * distance(points) / oldDistance,
          {clientX:(points[0].x+points[1].x)/2,clientY:(points[0].y+points[1].y)/2});
      } else if (this.zoom > 1) {
        this.x += event.clientX - previous.x;
        this.y += event.clientY - previous.y;
        this.clamp();
      }
    },
    pointerUp(event) { this.pointers.delete(event.pointerId); this.dragging = this.pointers.size > 0; },
    key(event) {
      if (!['+','=','-','0'].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation();
      if (event.key === '0') this.fit(); else this.setZoom(this.zoom * (event.key === '-' ? 1/1.5 : 1.5));
    },
  },
};
