// The hero floor: a plane of embossed tiles, tilted in CSS 3D.
//
// Pointer: the tile under the pointer rises into a slab of a random height and colour. When the
// pointer moves on, that slab sinks slowly, so the pointer's path leaves a trail of slabs at
// falling heights behind it.
//
// Scroll: the stage is sticky. As the page scrolls, the panel fades, one slab near the bottom
// centre rises, the floor zooms into that slab's top, and a green veil closes over it so the next
// section continues in the same colour.
//
// Nothing here reads data or the network; it only builds elements and reacts to the pointer and
// the scroll position.

const SIZE = 14;
const HEIGHTS = [0.45, 0.7, 0.95, 1.2] as const; // slab heights, in units of --H (see the CSS)
const TONES = ["r5", "r5", "r3", "r3", "r2", "r4", "r1"] as const; // teal and green most often
const RISE = 14; // how fast a slab climbs to its height (per second, exponential)
const SINK = 1.7; // how fast a slab left behind sinks: slow, so the path stays visible
const DIVE_HEIGHT = 1.5; // how tall the slab we dive into grows
const RIPPLE = 0.16; // how far the neighbours of a rising slab lift before settling

type Tile = { el: HTMLElement; row: number; col: number; h: number; target: number; tone: string };

const reduceMotion = (): boolean => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));
const smooth = (a: number, b: number, x: number): number => {
  const t = clamp01((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};
const pick = <T>(list: readonly T[]): T => list[Math.floor(Math.random() * list.length)] as T;

export function startHero(): void {
  const dive = document.querySelector<HTMLElement>("#top");
  const stage = document.querySelector<HTMLElement>("#stage");
  const surface = document.querySelector<HTMLElement>("#surface");
  const grid = document.querySelector<HTMLElement>("#grid");
  const panel = document.querySelector<HTMLElement>("#panel");
  const veil = document.querySelector<HTMLElement>("#veil");
  if (!dive || !stage || !surface || !grid || !panel || !veil) return;

  const tiles: Tile[] = [];
  const byElement = new WeakMap<Element, Tile>();
  const fragment = document.createDocumentFragment();
  for (let row = 0; row < SIZE; row++) {
    for (let col = 0; col < SIZE; col++) {
      const el = document.createElement("i");
      el.append(document.createElement("b"));
      const tile: Tile = { el, row, col, h: 0, target: 0, tone: "r5" };
      tiles.push(tile);
      byElement.set(el, tile);
      fragment.append(el);
    }
  }
  grid.append(fragment);
  document.body.classList.add("floor-ready");

  const paint = (tile: Tile): void => {
    if (tile.h > 0.004) {
      tile.el.className = `up ${tile.tone}`;
      tile.el.style.setProperty("--h", tile.h.toFixed(3));
    } else {
      tile.h = 0;
      tile.el.className = "";
      tile.el.style.removeProperty("--h");
    }
  };

  if (reduceMotion()) return; // a still floor, and no dive: the page simply scrolls

  // ---- pointer trail -------------------------------------------------------------------------
  let diveTile: Tile | null = null;
  let diving = false;
  let frame = 0;
  let last = 0;
  const step = (now: number): void => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    let moving = false;
    for (const tile of tiles) {
      if (diving && tile === diveTile) continue; // the scroll drives this one
      const gap = tile.target - tile.h;
      if (Math.abs(gap) < 0.003) {
        if (tile.h !== tile.target) {
          tile.h = tile.target;
          paint(tile);
        }
        continue;
      }
      tile.h += gap * (1 - Math.exp(-(gap > 0 ? RISE : SINK) * dt));
      paint(tile);
      moving = true;
    }
    frame = moving ? requestAnimationFrame(step) : 0;
  };
  const run = (): void => {
    if (!frame) {
      last = performance.now();
      frame = requestAnimationFrame(step);
    }
  };

  const at = (row: number, col: number): Tile | undefined =>
    row >= 0 && row < SIZE && col >= 0 && col < SIZE ? tiles[row * SIZE + col] : undefined;
  let current: Tile | null = null;
  const raise = (tile: Tile | null): void => {
    if (tile === current) return;
    if (current) current.target = 0; // left behind: it sinks slowly, leaving the trail
    current = tile;
    if (tile) {
      if (tile.h < 0.05) tile.tone = pick(TONES);
      let height = pick(HEIGHTS);
      if (height === tile.target) height = pick(HEIGHTS);
      tile.target = height;
      // Ripple: the four tiles touching it lift a little and settle straight back.
      for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
        const n = at(tile.row + dr, tile.col + dc);
        if (!n || n.h > 0.1) continue;
        n.tone = pick(TONES);
        n.target = RIPPLE;
        window.setTimeout(() => {
          if (n !== current && n.target === RIPPLE) {
            n.target = 0;
            run();
          }
        }, 170);
      }
    }
    run();
  };

  const tileAt = (event: Event): Tile | null => {
    const el = (event.target as Element | null)?.closest("#grid > i");
    return el ? (byElement.get(el) ?? null) : null;
  };
  stage.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch" || diving) return;
    raise(tileAt(event)); // over the panel this is null, so the last slab starts to sink
  });
  stage.addEventListener("pointerleave", () => raise(null));
  stage.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch" || diving) return;
    raise(tileAt(event));
    window.setTimeout(() => raise(null), 700);
  });

  // ---- scroll dive ---------------------------------------------------------------------------
  let originX = 0;
  let originY = 0;
  let cell = 0;
  /** Find the tile nearest the bottom centre of the screen, with the floor at rest. */
  const measure = (): void => {
    surface.style.transform = "";
    const cx = window.innerWidth / 2;
    const cy = stage.clientHeight * 0.8;
    let best: Tile | null = null;
    let bestDistance = Infinity;
    for (const tile of tiles) {
      const r = tile.el.getBoundingClientRect();
      const d = Math.hypot(r.left + r.width / 2 - cx, r.top + r.height / 2 - cy);
      if (d < bestDistance) {
        bestDistance = d;
        best = tile;
      }
    }
    if (best && best !== diveTile) {
      if (diveTile) diveTile.target = 0;
      diveTile = best;
    }
    if (diveTile) {
      const stageTop = stage.getBoundingClientRect().top;
      const r = diveTile.el.getBoundingClientRect();
      originX = r.left + r.width / 2;
      originY = r.top - stageTop + r.height / 2;
    }
    cell = (grid.firstElementChild as HTMLElement | null)?.offsetWidth ?? 0;
  };

  let pending = false;
  const update = (): void => {
    pending = false;
    const travel = dive.offsetHeight - stage.clientHeight;
    const p = travel > 0 ? clamp01(-dive.getBoundingClientRect().top / travel) : 0;

    const fade = smooth(0, 0.18, p);
    panel.style.opacity = String(1 - fade);
    panel.style.transform = `translateY(${(fade * 40).toFixed(1)}px)`;
    panel.style.visibility = fade > 0.98 ? "hidden" : "";

    const shade = smooth(0.62, 0.97, p);
    veil.style.opacity = String(shade);
    stage.dataset.tone = shade > 0.5 ? "dark" : "light";

    const wasDiving = diving;
    diving = p > 0.004;
    if (!diveTile) return;
    if (diving) {
      if (!wasDiving) raise(null);
      const tile = diveTile;
      tile.tone = "r5";
      tile.h = tile.target = DIVE_HEIGHT * smooth(0.04, 0.5, p);
      paint(tile);
      // Zoom towards the top face of the rising slab, and bring it to the middle of the screen.
      const z = smooth(0.18, 1, p);
      const scale = 1 + 9 * z * z;
      const lift = tile.h * cell * 0.8 * 0.79; // --H is 0.8 cells; the floor is tilted 52 degrees
      const oy = originY - lift;
      const dx = (window.innerWidth / 2 - originX) * z;
      const dy = (stage.clientHeight * 0.48 - oy) * z;
      surface.style.transformOrigin = `${originX.toFixed(1)}px ${oy.toFixed(1)}px`;
      surface.style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px) scale(${scale.toFixed(3)})`;
    } else if (wasDiving) {
      surface.style.transform = "";
      diveTile.target = 0;
      run();
    }
  };
  const schedule = (): void => {
    if (!pending) {
      pending = true;
      requestAnimationFrame(update);
    }
  };
  measure();
  update();
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", () => {
    measure();
    schedule();
  });
}
