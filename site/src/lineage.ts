// The lineage page: every relation Currant verified on the crawled docs, from
// lineage/lineage.json (written by scripts/build_lineage.py, which re-checks every quote word for
// word against the stored page). Crawled text is untrusted: it is inserted as text, never as HTML,
// and only http(s) links are made.

import { startChrome } from "./chrome";
import data from "./lineage/lineage.json";

startChrome();

type Span = { url: string; start: number; end: number; quote: string };
type Claim = Span & { id: string; subject: string; attribute: string; value: string; crawled: string };
type Evidence = Span & { role: string };
type Review = { verdict: string; note: string; source: string };
type Supersedes = { relation_id: string; basis: string; newer: Claim; older: Claim; evidence: Evidence[]; review: Review };
type Contested = { relation_id: string; a: Claim; b: Claim; evidence: Evidence[]; review: Review };
type Chain = { claims: string[]; branched: boolean };
type Corpus = {
  corpus: string;
  snapshot_date: string;
  corpus_hash: string;
  relate_run: { model: string; prompt_version: string };
  chains: Chain[];
  supersedes: Supersedes[];
  contested: Contested[];
};

const corpora = data.corpora as Corpus[];

const BASIS: Record<string, string> = {
  explicit_text: "The newer page says it replaces the older value",
  dated: "Both pages carry dates; the later one wins",
  crawl_diff: "The page changed between two crawls",
};

// What a person concluded on reading the relation (docs/drift or docs/LIMITATIONS).
const VERDICT: Record<string, { label: string; cls: string }> = {
  genuine: { label: "Reviewed: real", cls: "pill-code" },
  conflict: { label: "Reviewed: real conflict", cls: "pill-code" },
  "resolved-by-removal": { label: "Reviewed: real, since fixed", cls: "pill-code" },
  "false-positive": { label: "Reviewed: detector false positive", cls: "pill-bad" },
  "not-a-conflict": { label: "Reviewed: not a conflict", cls: "pill-bad" },
  "changed-between-crawls": { label: "Reviewed: real change, not an error", cls: "pill-code" },
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function link(url: string): HTMLElement {
  let safe = false;
  try {
    safe = ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    safe = false;
  }
  if (!safe) return el("span", "lin-url", url);
  const a = el("a", "lin-url", url.replace(/^https?:\/\//, ""));
  a.href = url;
  a.rel = "noopener";
  return a;
}

function quote(span: Span): HTMLElement {
  const q = el("blockquote", "lin-quote");
  q.append(el("span", "", span.quote));
  const meta = el("p", "lin-meta");
  meta.append(link(span.url), el("span", "", ` · characters ${span.start}–${span.end}`));
  q.append(meta);
  return q;
}

const LABEL = { old: "older", mid: "older", new: "newer", tip: "newest on this path" };

function claimNode(claim: Claim, state: "old" | "mid" | "new" | "tip"): HTMLElement {
  const node = el("li", `lin-node lin-${state}`);
  const head = el("div", "lin-head");
  head.append(el("span", "lin-value", claim.value));
  head.append(el("span", `pill ${state === "new" ? "pill-code" : "pill-model"}`, LABEL[state]));
  node.append(head, el("p", "lin-key", `${claim.subject} · ${claim.attribute} · crawled ${claim.crawled}`), quote(claim));
  return node;
}

function review(r: Review): HTMLElement {
  const box = el("div", "lin-review");
  const v = VERDICT[r.verdict] ?? { label: `Reviewed: ${r.verdict}`, cls: "pill-model" };
  box.append(el("span", `pill ${v.cls}`, v.label), el("p", "", r.note));
  const src = link(r.source);
  src.textContent = "Where this was reviewed";
  box.append(src);
  return box;
}

function step(rel: Supersedes): HTMLElement {
  const node = el("li", "lin-step");
  node.append(el("p", "lin-basis", `Detector: ${BASIS[rel.basis] ?? rel.basis}`));
  for (const ev of rel.evidence.filter((e) => e.role === "ordering")) {
    const q = el("p", "lin-order");
    q.append(el("span", "", "Ordering quote: "), el("code", "", ev.quote));
    node.append(q);
  }
  node.append(review(rel.review));
  return node;
}

function renderChains(corpus: Corpus): HTMLElement | null {
  if (!corpus.chains.length) return null;
  const claims = new Map<string, Claim>();
  const rel = new Map<string, Supersedes>();
  for (const r of corpus.supersedes) {
    claims.set(r.older.id, r.older);
    claims.set(r.newer.id, r.newer);
    rel.set(`${r.older.id}>${r.newer.id}`, r);
  }
  const block = el("div", "lin-corpus");
  block.append(el("h3", "", corpus.corpus));
  // Paths that start from the same replaced value are one story: one card, the branch said once.
  const byStart = new Map<string, Chain[]>();
  for (const chain of corpus.chains) {
    const start = chain.claims[0] ?? "";
    byStart.set(start, [...(byStart.get(start) ?? []), chain]);
  }
  for (const paths of byStart.values()) {
    const card = el("article", "lin-card");
    const branched = paths.some((p) => p.branched);
    if (branched) {
      card.append(el("p", "lin-branch", "This value was replaced by different values on different pages. There is no single latest value, so Currant will not pick one: it annotates and pulls nothing through a branch. Each path is shown below."));
    }
    paths.forEach((chain, n) => {
      if (n > 0) card.append(el("p", "lin-path", `Path ${n + 1}`));
      else if (paths.length > 1) card.append(el("p", "lin-path", "Path 1"));
      const list = el("ol", "lin-chain");
      chain.claims.forEach((id, i) => {
        if (i > 0) {
          const r = rel.get(`${chain.claims[i - 1]}>${id}`);
          if (r) list.append(step(r));
        }
        const last = i === chain.claims.length - 1;
        const claim = claims.get(id);
        const state = i === 0 ? "old" : !last ? "mid" : branched ? "tip" : "new";
        if (claim) list.append(claimNode(claim, state));
      });
      card.append(list);
    });
    block.append(card);
  }
  return block;
}

function renderContested(corpus: Corpus): HTMLElement | null {
  if (!corpus.contested.length) return null;
  const block = el("div", "lin-corpus");
  block.append(el("h3", "", corpus.corpus));
  // Real conflicts first: a drift-page note may point to one "listed above".
  const real = (p: Contested): number => (VERDICT[p.review.verdict]?.cls === "pill-code" ? 0 : 1);
  for (const pair of [...corpus.contested].sort((x, y) => real(x) - real(y))) {
    const card = el("article", "lin-card lin-pair");
    for (const side of [pair.a, pair.b]) {
      const col = el("div", "lin-side");
      col.append(el("span", "lin-value", side.value), el("p", "lin-key", `${side.subject} · ${side.attribute}`), quote(side));
      card.append(col);
    }
    const r = review(pair.review);
    r.classList.add("lin-span");
    card.append(r);
    block.append(card);
  }
  return block;
}

const chainsHost = document.querySelector<HTMLElement>("#chains-list");
const contestedHost = document.querySelector<HTMLElement>("#contested-list");
const runsHost = document.querySelector<HTMLElement>("#runs-list");
for (const corpus of corpora) {
  const c = renderChains(corpus);
  if (c && chainsHost) chainsHost.append(c);
  const p = renderContested(corpus);
  if (p && contestedHost) contestedHost.append(p);
  if (runsHost) {
    runsHost.append(
      el("li", "", `${corpus.corpus}: crawl of ${corpus.snapshot_date}, corpus hash ${corpus.corpus_hash.slice(0, 12)}…, detection ${corpus.relate_run.prompt_version} (${corpus.relate_run.model}); ${corpus.supersedes.length} replacements and ${corpus.contested.length} conflicts shown, each reviewed by hand.`),
    );
  }
}

const counts = document.querySelector<HTMLElement>("#lin-counts");
if (counts) {
  const sup = corpora.reduce((n, c) => n + c.supersedes.length, 0);
  const con = corpora.reduce((n, c) => n + c.contested.length, 0);
  const real = corpora.flatMap((c) => [...c.supersedes, ...c.contested]).filter((r) => ["genuine", "conflict", "resolved-by-removal", "changed-between-crawls"].includes(r.review.verdict)).length;
  counts.textContent = `${sup} replacements and ${con} conflicts the detector verified, from ${corpora.length} detection runs. Read by hand, ${real} of the ${sup + con} are real; the rest are labelled as false positives below.`;
}
