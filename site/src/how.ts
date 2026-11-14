// The "How it works" page. Its receipt anatomy is built from the committed demo receipt itself
// (a copy of examples/demo/receipt.json that a test keeps identical), so the fields shown cannot
// drift from what Currant actually writes. Everything is inserted as text, never as HTML.

import { startChrome } from "./chrome";
import receipt from "./demo/receipt.json";

startChrome();

const short = (hash: string): string => `${hash.slice(0, 12)}…${hash.slice(-6)}`;

type Row = { key: string; value: string; note: string };

const rows: Row[] = [
  {
    key: "receipt_id",
    value: short(receipt.receipt_id),
    note: "Names this receipt. Rebuilding the demo from scratch gives the same id every time.",
  },
  { key: "question", value: receipt.question, note: "What the model was asked." },
  {
    key: "mode",
    value: receipt.mode,
    note: "How the context was changed: here, superseded sentences were cut and their replacements pulled in.",
  },
  {
    key: "context_sha256",
    value: short(receipt.context_sha256),
    note: "The SHA-256 of the exact text the model was shown. Replay recomputes it; one changed character and it fails.",
  },
  { key: "context_chars", value: String(receipt.context_chars), note: "The length of that text." },
  {
    key: "corpus.corpus_hash",
    value: short(receipt.corpus.corpus_hash),
    note: "The crawled snapshot the claims came from, so a receipt cannot quietly switch sources.",
  },
  {
    key: "runs.extract",
    value: `${receipt.runs.extract.model} · ${receipt.runs.extract.prompt_version}`,
    note: "Which model and prompt version proposed the claims. In the demo they are written by hand, so it is deterministic.",
  },
  {
    key: "runs.relate",
    value: `${receipt.runs.relate.model} · ${receipt.runs.relate.prompt_version}`,
    note: "Which model and prompt version proposed which claim replaced which.",
  },
];

const ROLE: Record<string, string> = {
  older: "older",
  newer: "newer",
  ordering: "says which came first",
  other: "one side",
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

const fields = document.querySelector<HTMLElement>("#anatomy-fields");
if (fields) {
  fields.replaceChildren(
    ...rows.map((row) => {
      const item = el("div", "field");
      item.append(el("dt", "", row.key), el("dd", "value", row.value), el("dd", "gloss", row.note));
      return item;
    }),
  );
}

const actions = document.querySelector<HTMLElement>("#anatomy-actions");
if (actions) {
  actions.replaceChildren(
    ...receipt.actions.map((action) => {
      const card = el("li", `act act-${action.kind}`);
      card.append(el("p", "act-kind", action.kind.toUpperCase()));
      const quotes = el("ul", "act-quotes");
      for (const ev of action.evidence) {
        const line = el("li", "");
        line.append(
          el("span", "act-role", ROLE[ev.role] ?? ev.role),
          el("span", "act-quote", `“${ev.quote}”`),
          el("span", "act-where", `${ev.url.replace("https://", "")} · characters ${ev.start}–${ev.end}`),
        );
        quotes.append(line);
      }
      card.append(quotes);
      return card;
    }),
  );
}
