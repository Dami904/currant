"use strict";
// Receipt text is crawled from the web and untrusted: it is only ever shown with textContent.
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const getJson = async (url) => {
  const response = await fetch(url);
  if (!response.ok) throw new Error(url + " returned " + response.status);
  return response.json();
};
const listBox = document.getElementById("list");
const detail = document.getElementById("detail");

function quote(label, ref) {
  const box = el("div", undefined, "card");
  box.append(el("strong", label), el("p", "“" + ref.quote + "”"), el("code", ref.url));
  return box;
}

async function show(id, button) {
  for (const b of listBox.children) b.removeAttribute("aria-current");
  button.setAttribute("aria-current", "true");
  detail.replaceChildren(el("p", "Loading…", "muted"));
  try {
    const [receipt, context, replay] = await Promise.all([
      getJson("/receipts/" + id),
      fetch("/receipts/" + id + "/context").then((r) => r.text()),
      getJson("/receipts/" + id + "/replay"),
    ]);
    const out = [];
    out.push(el("h2", "Question"), el("p", receipt.question));
    const verdict = replay.ok
      ? "REPLAY OK: the context hash recomputes from the store"
      : "REPLAY FAILED";
    out.push(el("p", verdict, "status " + (replay.ok ? "ok" : "bad")));
    for (const problem of replay.problems || []) out.push(el("p", problem, "bad"));
    out.push(el("p", "context sha256 " + receipt.context_sha256, "muted"));
    out.push(el("h2", "What Currant did (" + receipt.actions.length + ")"));
    if (receipt.actions.length === 0) {
      out.push(el("p", "Nothing: no verified relation applied.", "muted"));
    }
    for (const action of receipt.actions) {
      const card = el("div", undefined, "card " + (action.kind === "redact" ? "cut" : action.kind));
      card.append(el("strong", action.kind.toUpperCase()));
      card.append(
        quote("Superseded sentence", action.target),
        quote("Current documentation", action.source),
      );
      for (const item of action.evidence) card.append(quote("Evidence: " + item.role, item));
      out.push(card);
    }
    out.push(el("h2", "Exact context sent to the model"), el("pre", context));
    out.push(el("p", "Check it yourself: currant replay <receipt.json> --db <store>", "muted"));
    detail.replaceChildren(...out);
  } catch (error) {
    detail.replaceChildren(el("p", String(error), "bad"));
  }
}

async function main() {
  try {
    const ids = await getJson("/receipts");
    if (ids.length === 0) listBox.append(el("p", "No receipts yet.", "muted"));
    for (const id of ids) {
      const button = el("button", id.slice(0, 16) + "…");
      button.addEventListener("click", () => show(id, button));
      listBox.append(button);
    }
  } catch (error) {
    listBox.append(el("p", String(error), "bad"));
  }
}
main();
