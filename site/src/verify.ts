// The receipt check: hash a pasted context in this browser and compare it with a pasted receipt.
// It starts with a copy of examples/real/ (a test keeps it byte-identical). Everything shown is
// inserted as text, never as HTML. The hash check sends nothing anywhere; the full replay sends
// the receipt (only when its button is pressed) to /api/replay, the read-only server replay.

import realContext from "./real/context.txt?raw";
import realReceipt from "./real/receipt.json?raw";

function sha256Hex(text: string): Promise<string> {
  return crypto.subtle
    .digest("SHA-256", new TextEncoder().encode(text))
    .then((buffer) => [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join(""));
}

function field(raw: string, name: string): string | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && name in parsed) {
      const value = (parsed as Record<string, unknown>)[name];
      return typeof value === "string" ? value : null;
    }
  } catch {
    return null;
  }
  return null;
}

function start(): void {
  const get = <T extends HTMLElement>(id: string): T => {
    const el = document.getElementById(id);
    if (!el) throw new Error(`verify markup is missing #${id}`);
    return el as T;
  };
  const context = get<HTMLTextAreaElement>("context");
  const receipt = get<HTMLTextAreaElement>("receipt");
  const claimed = get<HTMLElement>("claimed");
  const rid = get<HTMLElement>("rid");
  const verdict = get<HTMLElement>("verdict");

  function show(): void {
    claimed.textContent = field(receipt.value, "context_sha256") ?? "(no context_sha256 in the receipt)";
    rid.textContent = field(receipt.value, "receipt_id") ?? "(no receipt_id)";
    verdict.className = "result";
    verdict.textContent = "Not checked yet.";
  }

  function load(): void {
    context.value = realContext;
    receipt.value = realReceipt;
    show();
  }

  receipt.addEventListener("input", show);
  context.addEventListener("input", show);
  get<HTMLButtonElement>("reset").addEventListener("click", load);
  get<HTMLButtonElement>("check").addEventListener("click", async () => {
    const expected = field(receipt.value, "context_sha256");
    if (expected === null) {
      verdict.className = "result bad";
      verdict.textContent = "The receipt is not JSON with a context_sha256 field.";
      return;
    }
    verdict.className = "result";
    verdict.textContent = "Computing…";
    // A textarea turns CRLF into LF; receipts are built from LF text, so this is lossless for them.
    const actual = await sha256Hex(context.value);
    const ok = actual === expected;
    verdict.className = `result ${ok ? "ok" : "bad"}`;
    verdict.textContent = ok ? `MATCH  ${actual}` : `MISMATCH  recomputed ${actual}, receipt says ${expected}`;
  });
  const replayButton = get<HTMLButtonElement>("replay");
  const replayVerdict = get<HTMLElement>("replay-verdict");
  const replayProblems = get<HTMLElement>("replay-problems");
  const TIMEOUT_MS = 20_000;

  function showReplay(verdictText: string, cls: string, problems: string[]): void {
    replayVerdict.className = `result ${cls}`;
    replayVerdict.textContent = verdictText;
    replayProblems.replaceChildren(
      ...problems.map((p) => {
        const li = document.createElement("li");
        li.textContent = p;
        return li;
      }),
    );
  }

  replayButton.addEventListener("click", async () => {
    replayButton.disabled = true;
    showReplay("Replaying on the server…", "", []);
    const abort = new AbortController();
    const timer = window.setTimeout(() => abort.abort(), TIMEOUT_MS);
    try {
      const response = await fetch("/api/replay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: receipt.value,
        signal: abort.signal,
      });
      const reply: unknown = await response.json();
      const r = (reply && typeof reply === "object" ? reply : {}) as Record<string, unknown>;
      const verdictName = typeof r.verdict === "string" ? r.verdict : "UNKNOWN";
      const problems = Array.isArray(r.problems) ? r.problems.filter((p): p is string => typeof p === "string") : [];
      const store = r.store && typeof r.store === "object" ? (r.store as Record<string, unknown>) : null;
      const where = store && typeof store.name === "string" ? ` against ${store.name}` : "";
      const context = typeof r.context_sha256 === "string" ? ` Context ${r.context_sha256}` : "";
      if (response.ok && verdictName === "REPLAYED") {
        showReplay(`REPLAYED${where}: re-grounding reproduced this receipt exactly.${context}`, "ok", []);
      } else if (verdictName === "FAILED") {
        showReplay(`FAILED${where}: replay found ${problems.length} problem${problems.length === 1 ? "" : "s"}.`, "bad", problems);
      } else {
        showReplay(`UNKNOWN: the server could not decide. This is not a pass.`, "", problems);
      }
    } catch {
      // A timeout, a network error or a reply that is not JSON: undecided, never a pass or a fail.
      showReplay("UNKNOWN: the server did not answer (timeout or network error). This is not a pass.", "", []);
    } finally {
      window.clearTimeout(timer);
      replayButton.disabled = false;
    }
  });
  receipt.addEventListener("input", () => showReplay("", "", []));
  load();
}

start();
