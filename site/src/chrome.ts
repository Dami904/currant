// What every page shares: the brand card's menu, the top-right links turning light over dark
// sections, and sections revealing as they scroll into view.

export function startChrome(): void {
  // Reveal sections as they scroll into view. Without JS, or with reduced motion, all is shown.
  const reveal = document.querySelectorAll<HTMLElement>("[data-reveal]");
  if ("IntersectionObserver" in window && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const seen = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            seen.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.12 },
    );
    document.documentElement.classList.add("can-reveal");
    reveal.forEach((el) => seen.observe(el));
  }

  // The brand card's menu button opens a short list of the site's sections.
  const menuButton = document.querySelector<HTMLButtonElement>("#menu-btn");
  const menu = document.querySelector<HTMLElement>("#menu");
  if (menuButton && menu) {
    const setOpen = (open: boolean): void => {
      menu.hidden = !open;
      menuButton.setAttribute("aria-expanded", String(open));
      menuButton.setAttribute("aria-label", open ? "Close the menu" : "Open the menu");
    };
    menuButton.addEventListener("click", () => setOpen(Boolean(menu.hidden)));
    menu.addEventListener("click", (event) => {
      if ((event.target as Element | null)?.closest("a")) setOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !menu.hidden) {
        setOpen(false);
        menuButton.focus();
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (!menu.hidden && !(event.target as Element | null)?.closest(".brand-card")) setOpen(false);
    });
  }

  // The top-right links turn light while a dark section sits under them.
  const head = document.querySelector<HTMLElement>("#head");
  const dark = [...document.querySelectorAll<HTMLElement>('[data-tone="dark"], #stage')];
  if (head) {
    let pending = false;
    const tone = (): void => {
      pending = false;
      const y = 30;
      const under = dark.find((el) => {
        const r = el.getBoundingClientRect();
        return r.top <= y && r.bottom > y;
      });
      head.classList.toggle("on-dark", under?.dataset.tone === "dark");
      // Past the hero, the header gets a frosted bar so its links never sit on top of body text.
      head.classList.toggle("solid", window.scrollY > 40 && under?.id !== "stage");
    };
    window.addEventListener(
      "scroll",
      () => {
        if (!pending) {
          pending = true;
          requestAnimationFrame(tone);
        }
      },
      { passive: true },
    );
    tone();
  }
}
