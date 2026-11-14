// The interactive demo: the same documents, shown to a model with and without Currant, and a
// replay that recomputes the SHA-256 of the context in this browser and compares it with the
// receipt. The context and receipt are copies of examples/demo/ (a test keeps them identical).
// Everything shown is inserted as text, never as HTML.

import contextText from "./demo/context.txt?raw";
import receipt from "./demo/receipt.json";

type Mark = { find: string; cls: string };

const STALE = "Each API key may make 60 requests per minute.";
const REMOVED = "[REMOVED: superseded by newer documentation]";
const NOTICE_START = "<<<NOTICE: CONTESTED>>>";
const NOTICE_END = "<<<END NOTICE>>>\n";
const PULLED_START = "<<<PULLED EVIDENCE>>>";
const PULLED_END = "<<<END PULLED EVIDENCE>>>\n";

/** The same pages with nothing done to them: the notice and the pulled evidence are dropped and
 *  the cut sentence is put back. The 60-per-minute sentence is the one build_demo.py wrote. */
function withoutCurrant(text: string): string {
  const notice = text.slice(text.indexOf(NOTICE_START), text.indexOf(NOTICE_END) + NOTICE_END.length);
  const pulled = text.slice(text.indexOf(PULLED_START), text.indexOf(PULLED_END) + PULLED_END.length);
  return text.replace(notice, "").replace(pulled, "").replace(REMOVED, STALE);
}

const WITHOUT = withoutCurrant(contextText);

function blocks(text: string): Mark[] {
  const notice = text.slice(text.indexOf(NOTICE_START), text.indexOf(NOTICE_END) + NOTICE_END.length);
  const pulled = text.slice(text.indexOf(PULLED_START), text.indexOf(PULLED_END) + PULLED_END.length);
  return [
    { find: notice, cls: "m-contested" },
    { find: REMOVED, cls: "m-removed" },
    { find: pulled, cls: "m-pulled" },
  ];
}

function sha256Hex(text: string): Promise<string> {
  return crypto.subtle
    .digest("SHA-256", new TextEncoder().encode(text))
    .then((buffer) => [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join(""));
}

/** Show `text` with each marked phrase wrapped in <mark>. Marks are found, never trusted. */
function paint(target: HTMLElement, text: string, marks: Mark[]): void {
  const spans = marks
    .map((m) => ({ ...m, at: m.find ? text.indexOf(m.find) : -1 }))
    .filter((m) => m.at >= 0)
    .sort((a, b) => a.at - b.at);
  const out: Node[] = [];
  let cursor = 0;
  for (const m of spans) {
    if (m.at < cursor) continue;
    out.push(document.createTextNode(text.slice(cursor, m.at)));
    const el = document.createElement("mark");
    el.className = m.cls;
    el.textContent = m.find;
    out.push(el);
    cursor = m.at + m.find.length;
  }
  out.push(document.createTextNode(text.slice(cursor)));
  target.replaceChildren(...out);
}

export function startDemo(): void {
  const root = document.querySelector<HTMLElement>("#demo");
  if (!root) return;
  const q = <T extends HTMLElement>(selector: string): T => {
    const el = root.querySelector<T>(selector);
    if (!el) throw new Error(`demo markup is missing ${selector}`);
    return el;
  };
  const box = q<HTMLElement>("#ctx");
  const readout = q<HTMLElement>("#readout");
  const explain = q<HTMLElement>("#explain");
  const stored = q<HTMLElement>("#stored");
  const result = q<HTMLElement>("#result");
  const modes = [...root.querySelectorAll<HTMLButtonElement>("[data-mode]")];
  const replay = q<HTMLButtonElement>("#replay");
  const tamper = q<HTMLButtonElement>("#tamper");

  let mode: "without" | "with" = "with";
  let tampered = false;
  stored.textContent = receipt.context_sha256;

  const shown = (): string => {
    if (mode === "without") return WITHOUT;
    return tampered ? contextText.replace("120 requests", "121 requests") : contextText;
  };

  function draw(): void {
    const text = shown();
    if (mode === "without") {
      paint(box, text, [{ find: STALE, cls: "m-stale" }]);
      readout.textContent =
        "The old rate limit sits in the context next to the page that contradicts it, and nothing says which is current. This is the text a model would be handed.";
      explain.textContent = "Without Currant: the retrieved pages, untouched.";
    } else {
      paint(box, text, blocks(text));
      readout.textContent =
        "The superseded sentence is cut, its replacement is pulled in with the changelog line that proves it, and the two upload sizes are marked CONTESTED with both quotes. Nothing is guessed.";
      explain.textContent = "With Currant: the exact context the model is shown.";
    }
    for (const button of modes) button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    replay.disabled = mode === "without";
    tamper.disabled = mode === "without";
    tamper.textContent = tampered ? "Undo the change" : "Change one number";
    result.className = "result";
    result.textContent = mode === "without" ? "No receipt: nothing was done, so there is nothing to replay." : "Not checked yet.";
  }

  for (const button of modes) {
    button.addEventListener("click", () => {
      mode = button.dataset.mode === "without" ? "without" : "with";
      tampered = false;
      draw();
    });
  }
  tamper.addEventListener("click", () => {
    tampered = !tampered;
    draw();
  });
  replay.addEventListener("click", async () => {
    result.className = "result";
    result.textContent = "Computing…";
    const actual = await sha256Hex(shown());
    const ok = actual === receipt.context_sha256;
    result.className = `result ${ok ? "ok" : "bad"}`;
    result.textContent = ok
      ? `MATCH  ${actual}`
      : `MISMATCH  recomputed ${actual}, receipt says ${receipt.context_sha256}`;
  });
  draw();
}
