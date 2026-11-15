// The receipt check: hash a pasted context in this browser and compare it with a pasted receipt.
// It starts with a copy of examples/real/ (a test keeps it byte-identical). Everything shown is
// inserted as text, never as HTML, and nothing is sent anywhere.

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
  load();
}

start();
