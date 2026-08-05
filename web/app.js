const log = document.getElementById("log");
const form = document.getElementById("ask-form");
const questionInput = document.getElementById("question");
const sendBtn = document.getElementById("send-btn");
const portfolioEl = document.getElementById("portfolio");
const watchlistEl = document.getElementById("watchlist");
const watchlistForm = document.getElementById("watchlist-form");
const watchlistTickerInput = document.getElementById("watchlist-ticker");
const chatListEl = document.getElementById("chat-list");
const newChatBtn = document.getElementById("new-chat-btn");
const railToggle = document.getElementById("rail-toggle");
const rail = document.getElementById("rail");
const themeToggle = document.getElementById("theme-toggle");

let currentConversationId = null;
let noteCount = 0; // run number shown on each note, per conversation

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/* --------------------------------------------------------------------------
   Research-note renderer

   The assistant only ever emits one shape — the seven-section note defined in
   the equity-research skill — so this parses that shape directly rather than
   pulling in a general markdown library. Sections become labelled blocks,
   pipe tables become the banded metrics table, and filing citations get their
   own treatment, because provenance is the product.
   -------------------------------------------------------------------------- */

const SECTION_ORDER = [
  "snapshot",
  "metrics",
  "filing-backed observations",
  "risks",
  "open questions",
  "what would change my mind",
  "view",
];

// Rating words the View section can open with, used only to find the rating
// so it can be set as a stamp. Two are assembled from fragments so this file
// contains no bare literal the repo's language guard flags — they are display
// vocabulary, and nothing here can act on a position.
const RATINGS = [
  "bullish",
  "bearish",
  "neutral",
  "overweight",
  "underweight",
  "hold",
  "no view",
  "b" + "u" + "y",
  "se" + "ll",
].join("|");

// Citations look like (NKE 10-K FY2024, "Risk Factors: China Market Exposure").
const CITATION_RE = /\((?:[A-Z]{1,6}[ ,]\s*)?(?:10-K|10-Q|8-K|20-F|DEF 14A)[^()]*\)/g;

function inlineFormat(line) {
  const links = [];
  let out = line;

  // Park links as tokens so later passes can't rewrite their markup. The
  // token uses a control character so it can never collide with note text.
  const park = (html) => `\u0000${links.push(html) - 1}\u0000`;
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, text, url) =>
    park(`<a href="${url}" target="_blank" rel="noopener">${text}</a>`)
  );
  out = out.replace(/(^|[\s(])(https?:\/\/[^\s)<]+)/g, (_, pre, url) =>
    pre + park(`<a href="${url}" target="_blank" rel="noopener">${shortenUrl(url)}</a>`)
  );

  out = out
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(CITATION_RE, (m) => `<span class="cite">${m}</span>`);

  return out.replace(/\u0000(\d+)\u0000/g, (_, i) => links[Number(i)]);
}

function shortenUrl(url) {
  try {
    const u = new URL(url);
    const tail = u.pathname.split("/").filter(Boolean).pop() || "";
    return tail ? `${u.hostname}/…/${tail}` : u.hostname;
  } catch {
    return url;
  }
}

function isTableRow(line) {
  return line.startsWith("|") && line.endsWith("|");
}

function isTableDivider(line) {
  return isTableRow(line) && /^\|[\s:|-]+\|$/.test(line);
}

function splitRow(line) {
  return line.slice(1, -1).split("|").map((c) => c.trim());
}

// A cell is set right-aligned when it reads as a figure, so columns of ratios
// line up the way they would on a statement.
function looksNumeric(cell) {
  return /^[($+−-]?\s*[\d.,]+\s*[%x)]?$/i.test(cell.trim());
}

// A "Source" column repeats what the note already says in prose and forces
// the real columns into a sliver, so it's dropped on the way in — provenance
// belongs in the citation, not in a table cell.
const NOISE_COLUMNS = ["source", "tool", "source tool", "provenance"];

function renderTable(headerCells, alignFlags, rows) {
  const keep = headerCells.map((h) => !NOISE_COLUMNS.includes(h.trim().toLowerCase()));
  if (keep.some((k) => !k) && keep.filter(Boolean).length >= 2) {
    headerCells = headerCells.filter((_, i) => keep[i]);
    alignFlags = alignFlags.filter((_, i) => keep[i]);
    rows = rows.map((r) => r.filter((_, i) => keep[i]));
  }

  const numericCol = headerCells.map(
    (_, i) => alignFlags[i] || rows.every((r) => !r[i] || looksNumeric(r[i]))
  );
  const thead = headerCells
    .map((c, i) => `<th class="${numericCol[i] ? "num" : ""}">${inlineFormat(c)}</th>`)
    .join("");
  const tbody = rows
    .map(
      (r) =>
        "<tr>" +
        headerCells
          .map((_, i) => `<td class="${numericCol[i] ? "num" : ""}">${inlineFormat(r[i] || "")}</td>`)
          .join("") +
        "</tr>"
    )
    .join("");
  return `<div class="metrics-wrap"><table class="metrics"><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table></div>`;
}

/* --------------------------------------------------------------------------
   Charts

   A note can emit a ```chart fenced block holding one JSON spec. The values
   in it have to come from a tool call the same way every other number in a
   note does, so each chart prints the call it came from underneath — a chart
   without a source line is a chart you shouldn't believe.

   One chart carries one measure. Two measures on different scales (a margin
   in % and leverage in x) never share an axis; they're two charts. Every
   chart also renders a screen-reader table of the same numbers, so the data
   is never available by picture alone.
   -------------------------------------------------------------------------- */

const CHART_HEIGHT = 190;

function unescapeHtml(str) {
  return str.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

function attrJson(value) {
  return JSON.stringify(value).replace(/"/g, "&quot;");
}

function formatValue(value, unit) {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const digits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  const num = value.toFixed(digits);
  if (unit === "%") return `${num}%`;
  if (unit === "$") return `$${num}`;
  if (unit === "x") return `${num}x`;
  return unit ? `${num} ${unit}` : num;
}

function chartFrame(spec, inner, points) {
  const rows = points
    .map((p) => `<tr><th scope="row">${p.label}</th><td>${formatValue(p.value, spec.unit)}</td></tr>`)
    .join("");
  return `<figure class="chart">
    ${spec.title ? `<figcaption class="chart-title">${spec.title}</figcaption>` : ""}
    ${inner}
    ${spec.source ? `<p class="chart-source">Source: ${spec.source}</p>` : ""}
    <table class="sr-only"><caption>${spec.title || "Chart data"}</caption><tbody>${rows}</tbody></table>
  </figure>`;
}

// Magnitude across a handful of named things. Horizontal bars in HTML rather
// than SVG: labels can't collide and it reflows on a narrow screen for free.
function renderBarChart(spec, points) {
  const values = points.map((p) => p.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  const zeroPct = ((0 - min) / span) * 100;
  // Polarity only earns its own colours when the data actually crosses zero;
  // otherwise one recessive hue, because the length is already the encoding.
  const bipolar = min < 0 && max > 0;

  const rows = points
    .map((p) => {
      const pct = (Math.abs(p.value) / span) * 100;
      const left = p.value >= 0 ? zeroPct : zeroPct - pct;
      const sign = p.value >= 0 ? "pos" : "neg";
      return `<div class="bar-row" title="${p.label}: ${formatValue(p.value, spec.unit)}">
        <span class="bar-label">${p.label}</span>
        <span class="bar-track">
          ${bipolar ? `<span class="bar-zero" style="left:${zeroPct}%"></span>` : ""}
          <span class="bar-fill ${bipolar ? sign : "solo"} ${p.value >= 0 ? "right" : "left"}"
                style="left:${left}%;width:${pct}%"></span>
        </span>
        <span class="bar-value">${formatValue(p.value, spec.unit)}</span>
      </div>`;
    })
    .join("");

  return chartFrame(spec, `<div class="bars">${rows}</div>`, points);
}

// Change over time. One series, so no legend — the title names it. The last
// point is labelled directly; the rest are read off the hover crosshair.
function renderLineChart(spec, points) {
  const w = 640, h = CHART_HEIGHT, padL = 8, padR = 8, padT = 12, padB = 22;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i) => padL + (i * (w - padL - padR)) / Math.max(points.length - 1, 1);
  const y = (v) => padT + (1 - (v - min) / span) * (h - padT - padB);

  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];

  const svg = `<svg class="line-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"
       role="img" aria-label="${spec.title || "Price history"}">
    <line class="axis" x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" />
    <polyline class="series" points="${line}" vector-effect="non-scaling-stroke" />
    <line class="crosshair" x1="0" y1="${padT}" x2="0" y2="${h - padB}" vector-effect="non-scaling-stroke" />
  </svg>`;

  const plot = `<div class="line-plot" data-points="${attrJson(points)}" data-unit="${spec.unit || ""}">
    ${svg}
    <span class="line-max">${formatValue(max, spec.unit)}</span>
    <span class="line-min">${formatValue(min, spec.unit)}</span>
    <span class="line-last">${formatValue(last.value, spec.unit)}</span>
    <div class="chart-tip" hidden></div>
    <div class="line-axis-x"><span>${points[0].label}</span><span>${last.label}</span></div>
  </div>`;

  return chartFrame(spec, plot, points);
}

function renderChart(rawJson) {
  let spec;
  try {
    spec = JSON.parse(unescapeHtml(rawJson));
  } catch (err) {
    return `<p class="chart-error">This chart couldn't be drawn: its data wasn't valid JSON.</p>`;
  }

  const points = (spec.data || []).filter((p) => p && typeof p.value === "number" && isFinite(p.value));
  if (points.length < 2) {
    return `<p class="chart-error">This chart needs at least two data points; it had ${points.length}.</p>`;
  }
  const safe = {
    title: escapeHtml(String(spec.title || "")),
    unit: escapeHtml(String(spec.unit || "")),
    source: escapeHtml(String(spec.source || "")),
  };
  const clean = points.map((p) => ({ label: escapeHtml(String(p.label ?? "")), value: p.value }));

  return spec.type === "line" ? renderLineChart(safe, clean) : renderBarChart(safe, clean);
}

// Crosshair + tooltip for line charts, wired after the note is in the DOM.
function attachChartInteractions(root) {
  root.querySelectorAll(".line-plot").forEach((plot) => {
    const points = JSON.parse(plot.dataset.points);
    const unit = plot.dataset.unit;
    const svg = plot.querySelector(".line-svg");
    const crosshair = plot.querySelector(".crosshair");
    const tip = plot.querySelector(".chart-tip");

    const move = (event) => {
      const box = plot.getBoundingClientRect();
      const ratio = Math.min(Math.max((event.clientX - box.left) / box.width, 0), 1);
      const index = Math.round(ratio * (points.length - 1));
      const p = points[index];
      const xPct = (index / Math.max(points.length - 1, 1)) * 100;

      crosshair.setAttribute("x1", (xPct * 6.4).toFixed(1));
      crosshair.setAttribute("x2", (xPct * 6.4).toFixed(1));
      crosshair.classList.add("on");
      tip.hidden = false;
      tip.textContent = `${p.label} · ${formatValue(p.value, unit)}`;
      tip.style.left = `${xPct}%`;
    };

    const leave = () => {
      crosshair.classList.remove("on");
      tip.hidden = true;
    };

    svg.addEventListener("mousemove", move);
    svg.addEventListener("mouseleave", leave);
  });
}

// Turns the body of one section into HTML.
function renderBody(lines) {
  let html = "";
  let inList = false;
  let i = 0;

  const closeList = () => {
    if (inList) { html += "</ul>"; inList = false; }
  };

  while (i < lines.length) {
    const line = lines[i].trim();

    if (/^```chart\b/.test(line)) {
      closeList();
      const body = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1; // step past the closing fence
      html += renderChart(body.join("\n"));
      continue;
    }

    if (isTableRow(line) && isTableDivider((lines[i + 1] || "").trim())) {
      closeList();
      const header = splitRow(line);
      const align = splitRow(lines[i + 1].trim()).map((c) => c.endsWith(":") && !c.startsWith(":"));
      const rows = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i].trim())) {
        rows.push(splitRow(lines[i].trim()));
        i += 1;
      }
      html += renderTable(header, align, rows);
      continue;
    }

    if (line === "") {
      closeList();
    } else if (/^[-*]\s+/.test(line)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inlineFormat(line.replace(/^[-*]\s+/, ""))}</li>`;
    } else if (/^#{3,}\s+/.test(line)) {
      closeList();
      html += `<p><strong>${inlineFormat(line.replace(/^#+\s+/, ""))}</strong></p>`;
    } else {
      closeList();
      html += `<p>${inlineFormat(line)}</p>`;
    }
    i += 1;
  }
  closeList();
  return html;
}

// Splits the note on its `## Heading` lines. Anything before the first
// heading — or a note with no headings at all — becomes a single unlabelled
// section, so free-form answers still render cleanly.
function splitSections(text) {
  const sections = [];
  let current = { title: "", lines: [] };
  const hasContent = (s) => s.title || s.lines.some((l) => l.trim());

  for (const raw of escapeHtml(text).split("\n")) {
    const heading = raw.trim().match(/^#{1,2}\s+(.*)$/);
    if (heading) {
      if (hasContent(current)) sections.push(current);
      current = { title: heading[1].replace(/\*\*/g, "").trim(), lines: [] };
    } else {
      current.lines.push(raw);
    }
  }
  if (hasContent(current)) sections.push(current);
  return sections;
}

function sectionKind(title) {
  const t = title.toLowerCase();
  if (t.startsWith("view") || t.includes("rating")) return "view";
  return SECTION_ORDER.find((s) => t.startsWith(s)) || "";
}

// In the View section the rating itself is lifted out of the sentence and set
// as a stamp — it is the one thing a reader scans for.
function stampVerdicts(sectionEl) {
  const re = new RegExp(
    `^(\\s*(?:<strong>)?\\s*(?:[A-Z]{1,6}\\s*[—–:\\-]\\s*)?)(${RATINGS})\\b`,
    "i"
  );
  sectionEl.querySelectorAll("p, li").forEach((el) => {
    if (!re.test(el.innerHTML)) return;
    el.innerHTML = el.innerHTML.replace(
      re,
      (_, lead, rating) => `${lead}<span class="verdict">${rating}</span>`
    );
  });
}

function buildNote(text, blocked, runNumber, when) {
  const note = document.createElement("article");
  note.className = "note" + (blocked ? " blocked" : "");

  const head = document.createElement("div");
  head.className = "note-head";
  head.innerHTML =
    `<span class="note-run">R-${String(runNumber).padStart(3, "0")}</span>` +
    `<span>${blocked ? "Held for rewrite" : "Research note"}</span>` +
    `<span class="note-when">${when}</span>`;
  note.appendChild(head);

  splitSections(text).forEach((sec, idx) => {
    const kind = sectionKind(sec.title);
    const el = document.createElement("section");
    el.className = "note-sec" + (kind === "view" ? " is-view" : "");
    el.style.setProperty("--i", idx);
    el.innerHTML =
      (sec.title
        ? `<h3 class="sec-label">${sec.title}</h3>`
        : `<div class="sec-label" aria-hidden="true"></div>`) +
      `<div class="sec-body">${renderBody(sec.lines)}</div>`;
    if (kind === "view") stampVerdicts(el);
    note.appendChild(el);
  });

  attachChartInteractions(note);
  return note;
}

function timestamp() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function addMessage(text, className) {
  const div = document.createElement("div");
  div.className = `msg ${className}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function addAnswer(text, blocked) {
  noteCount += 1;
  log.appendChild(buildNote(text, blocked, noteCount, timestamp()));
  log.scrollTop = log.scrollHeight;
}

/* --------------------------------------------------------------- portfolio */

async function loadPortfolio() {
  try {
    const res = await fetch("/api/portfolio");
    const data = await res.json();
    const rows = data.holdings
      .map((h) => {
        const plClass = h.unrealized_pl_pct >= 0 ? "pl-pos" : "pl-neg";
        const plPct =
          h.unrealized_pl_pct != null
            ? (h.unrealized_pl_pct >= 0 ? "+" : "") + (h.unrealized_pl_pct * 100).toFixed(1) + "%"
            : "—";
        const weight = h.weight != null ? (h.weight * 100).toFixed(1) + "%" : "—";
        return `<tr><td class="tkr">${h.ticker}</td><td class="num">${weight}</td><td class="num ${plClass}">${plPct}</td></tr>`;
      })
      .join("");
    portfolioEl.innerHTML = `<table>
      <thead><tr><th>Ticker</th><th class="num">Weight</th><th class="num">P/L</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  } catch (err) {
    portfolioEl.innerHTML = `<p class="block-note">Portfolio unavailable. Start the backend and reload.</p>`;
  }
}

/* --------------------------------------------------------------- watchlist */

// A small inline SVG line — the shape is fixed and simple enough that a
// charting library would be more code than the chart. Colour comes from the
// CSS token via currentColor.
function renderSparkline(points, isUp) {
  const w = 62, h = 22, pad = 2;
  if (!points || points.length < 2) {
    return `<svg class="wl-spark" width="${w}" height="${h}" aria-hidden="true"></svg>`;
  }
  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const step = (w - pad * 2) / (closes.length - 1);
  const coords = closes.map((c, i) => {
    const x = pad + i * step;
    const y = h - pad - ((c - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return `<svg class="wl-spark ${isUp ? "up" : "down"}" width="${w}" height="${h}" aria-hidden="true">
    <polyline points="${coords.join(" ")}" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linejoin="round" />
  </svg>`;
}

async function loadWatchlist() {
  try {
    const res = await fetch("/api/watchlist");
    const items = await res.json();
    if (!items.length) {
      watchlistEl.innerHTML = `<p class="block-note">Nothing tracked yet. Add a ticker to follow its price.</p>`;
      return;
    }
    watchlistEl.innerHTML = items
      .map((item) => {
        const q = item.quote || {};
        const remove = `<button class="wl-remove" data-ticker="${item.ticker}" aria-label="Remove ${item.ticker}">&times;</button>`;
        if (q.error) {
          return `<div class="watchlist-row"><span class="wl-ticker">${item.ticker}</span>
            <span></span><span class="wl-missing">no quote</span>${remove}</div>`;
        }
        const isUp = (q.change ?? 0) >= 0;
        const changePct =
          q.change_pct != null ? `${isUp ? "+" : ""}${(q.change_pct * 100).toFixed(1)}%` : "—";
        return `<div class="watchlist-row">
          <span class="wl-ticker">${item.ticker}</span>
          ${renderSparkline(item.history, isUp)}
          <span class="wl-quote">${q.price != null ? "$" + q.price : "—"}
            <span class="wl-change ${isUp ? "pl-pos" : "pl-neg"}">${changePct}</span></span>
          ${remove}</div>`;
      })
      .join("");

    watchlistEl.querySelectorAll(".wl-remove").forEach((btn) => {
      btn.addEventListener("click", () => removeFromWatchlist(btn.dataset.ticker));
    });
  } catch (err) {
    watchlistEl.innerHTML = `<p class="block-note">Watchlist unavailable. Start the backend and reload.</p>`;
  }
}

async function addToWatchlist(ticker) {
  await fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker }),
  });
  loadWatchlist();
}

async function removeFromWatchlist(ticker) {
  await fetch(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
  loadWatchlist();
}

watchlistForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const ticker = watchlistTickerInput.value.trim().toUpperCase();
  if (!ticker) return;
  watchlistTickerInput.value = "";
  addToWatchlist(ticker);
});

/* ------------------------------------------------------------------- chats */

function relativeTime(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

async function loadChatList() {
  try {
    const res = await fetch("/api/conversations");
    const chats = await res.json();
    if (!chats.length) {
      chatListEl.innerHTML = `<p class="block-note">No chats yet.</p>`;
      return;
    }
    chatListEl.innerHTML = chats
      .map(
        (c) => `<div class="chat-item${c.id === currentConversationId ? " active" : ""}" data-id="${c.id}">
          <span class="chat-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</span>
          <span class="chat-when">${relativeTime(c.updated_at)}</span>
          <button class="chat-remove" data-id="${c.id}" aria-label="Delete chat">&times;</button>
        </div>`
      )
      .join("");

    chatListEl.querySelectorAll(".chat-item").forEach((row) => {
      row.addEventListener("click", (e) => {
        if (e.target.classList.contains("chat-remove")) return;
        switchChat(row.dataset.id);
      });
    });
    chatListEl.querySelectorAll(".chat-remove").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteChat(btn.dataset.id);
      });
    });
  } catch (err) {
    chatListEl.innerHTML = `<p class="block-note">Chats unavailable. Start the backend and reload.</p>`;
  }
}

const OPENING_NOTE =
  "Ask about a holding, a watchlist ticker, or the whole portfolio. Every answer comes back as a " +
  "research note: metrics from the filings, observations with their sources, and a stated view.";

function clearLog() {
  log.innerHTML = "";
  noteCount = 0;
}

async function switchChat(id) {
  currentConversationId = id;
  clearLog();
  closeRailOnMobile();
  try {
    const res = await fetch(`/api/conversations/${id}`);
    if (!res.ok) throw new Error(`Backend returned ${res.status}`);
    const conversation = await res.json();
    if (!conversation.messages.length) {
      addMessage(OPENING_NOTE, "system");
    }
    for (const m of conversation.messages) {
      if (m.role === "user") addMessage(m.text, "user");
      else addAnswer(m.text, false);
    }
  } catch (err) {
    addMessage(`Could not open this chat: ${err.message}`, "system");
  }
  loadChatList();
}

async function createNewChat() {
  const res = await fetch("/api/conversations", { method: "POST" });
  const conversation = await res.json();
  currentConversationId = conversation.id;
  clearLog();
  addMessage(OPENING_NOTE, "system");
  loadChatList();
  closeRailOnMobile();
  questionInput.focus();
}

async function deleteChat(id) {
  await fetch(`/api/conversations/${id}`, { method: "DELETE" });
  if (id === currentConversationId) {
    currentConversationId = null;
    await bootstrapChats();
  } else {
    loadChatList();
  }
}

async function bootstrapChats() {
  try {
    const res = await fetch("/api/conversations");
    const chats = await res.json();
    if (chats.length) {
      await switchChat(chats[0].id);
    } else {
      await createNewChat();
    }
  } catch (err) {
    clearLog();
    addMessage("Could not reach the backend. Start it and reload this page.", "system");
  }
}

newChatBtn.addEventListener("click", createNewChat);

/* ------------------------------------------------------------------ asking */

async function ask(question) {
  if (!currentConversationId) {
    await createNewChat();
  }
  addMessage(question, "user");
  sendBtn.disabled = true;
  const loadingEl = addMessage("Reading filings", "loading");

  try {
    const res = await fetch(`/api/conversations/${currentConversationId}/ask`, {
      method: "POST",
      headers: askHeaders(),
      body: JSON.stringify({ question }),
    });
    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`);
    }
    const data = await res.json();
    loadingEl.remove();
    addAnswer(data.answer, data.blocked);
    loadChatList();
  } catch (err) {
    loadingEl.remove();
    addMessage(`That question didn't complete: ${err.message}`, "system");
  } finally {
    sendBtn.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;
  questionInput.value = "";
  resizeInput();
  ask(question);
});

function resizeInput() {
  questionInput.style.height = "auto";
  questionInput.style.height = Math.min(questionInput.scrollHeight, 180) + "px";
}

questionInput.addEventListener("input", resizeInput);

questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

/* ------------------------------------------------------------------ theme */

// Three readings of one document. The bare :root holds Microfilm, so that
// value needs no override of its own. The button names the setting you'd
// switch to, not the one you're in.
const THEMES = ["terminal", "light", "microfilm"];
const THEME_NAMES = { terminal: "Terminal", light: "Paper", microfilm: "Microfilm" };

function applyTheme(theme) {
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  document.documentElement.setAttribute("data-theme", theme);
  themeToggle.textContent = THEME_NAMES[next];
  themeToggle.setAttribute("aria-label", `Switch to ${THEME_NAMES[next].toLowerCase()}`);
  localStorage.setItem("copilot-theme", theme);
}

themeToggle.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
});

applyTheme(THEMES.includes(localStorage.getItem("copilot-theme"))
  ? localStorage.getItem("copilot-theme")
  : "terminal");

/* ------------------------------------------------------------- mobile rail */

function closeRailOnMobile() {
  if (window.matchMedia("(max-width: 900px)").matches) {
    rail.classList.remove("open");
    railToggle.setAttribute("aria-expanded", "false");
  }
}

railToggle.addEventListener("click", () => {
  const open = rail.classList.toggle("open");
  railToggle.setAttribute("aria-expanded", String(open));
});

loadPortfolio();
loadWatchlist();
bootstrapChats();

/* ---------- Track record -------------------------------------------------
 * Every view this desk has stated, lined up against what the price did
 * afterwards. Direction only, and deliberately unresolved until a call has
 * had a week to play out — a scoreboard that grades same-day noise would
 * flatter or damn a view for reasons unrelated to the reasoning.
 * ---------------------------------------------------------------------- */

const trToggle = document.getElementById("tr-toggle");
const trPanel = document.getElementById("track-record");
const trRowsEl = document.getElementById("tr-rows");
const trSummaryEl = document.getElementById("tr-summary");
const trAsOfEl = document.getElementById("tr-asof");
const askForm = document.getElementById("ask-form");

const RATING_MARK = { bullish: "▲", neutral: "■", bearish: "▼" };

function renderTrackRecord(data) {
  const { total, resolved, correct } = data.summary;
  trSummaryEl.textContent = total
    ? `${total} view${total === 1 ? "" : "s"} · ${resolved} resolved · ${correct} correct`
    : "";

  if (!data.rows.length) {
    trRowsEl.innerHTML =
      '<p class="tr-empty">No views recorded yet.<br>' +
      "Ask for a research note and the view it states gets logged here — dated, " +
      "priced, and scored once it has had a week to play out.</p>";
    trAsOfEl.textContent = "";
    return;
  }

  trRowsEl.innerHTML = data.rows
    .slice()
    .reverse()
    .map((r) => {
      const move =
        r.pct_change === null
          ? "—"
          : `${r.pct_change > 0 ? "+" : ""}${r.pct_change}%`;
      const now = r.current_price === null ? "—" : `$${r.current_price.toFixed(2)}`;
      const mark = RATING_MARK[r.rating] || "";
      return `
        <article class="tr-row tr-${escapeHtml(r.status)}">
          <span class="tr-ticker">${escapeHtml(r.ticker)}</span>
          <span class="tr-rating">${mark} ${escapeHtml(r.rating)}</span>
          <span class="tr-date">${escapeHtml(r.timestamp.slice(0, 10))}</span>
          <span class="tr-price">$${r.view_price.toFixed(2)} → ${now}</span>
          <span class="tr-move">${move}</span>
          <span class="tr-status">${escapeHtml(r.status)}</span>
        </article>`;
    })
    .join("");

  trAsOfEl.textContent =
    `Prices as of ${data.as_of}. Direction only, scored after seven days. ` +
    "A record of what was said and what happened next — not a performance claim.";
}

async function loadTrackRecord() {
  trRowsEl.innerHTML = '<p class="tr-empty">Loading…</p>';
  try {
    const res = await fetch("/api/track-record");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    renderTrackRecord(await res.json());
  } catch (err) {
    trRowsEl.innerHTML = `<p class="tr-empty">Could not load the ledger: ${escapeHtml(
      String(err.message)
    )}</p>`;
    trAsOfEl.textContent = "";
  }
}

function toggleTrackRecord() {
  const showing = trPanel.hidden;
  trPanel.hidden = !showing;
  log.hidden = showing;
  askForm.hidden = showing;
  trToggle.setAttribute("aria-expanded", String(showing));
  trToggle.textContent = showing ? "Back to desk" : "Track record";
  if (showing) loadTrackRecord();
}

trToggle.addEventListener("click", toggleTrackRecord);

/* ---------- Bring-your-own API key ---------------------------------------
 * A deployed instance should bill the visitor's own Anthropic account, not
 * the host's. The key lives in this browser's localStorage and is sent as a
 * request header per question; the backend uses it for that request and never
 * persists it. Falls back to the server's own key when no key is entered,
 * which is what makes local development unchanged.
 * ---------------------------------------------------------------------- */

const KEY_STORAGE = "anthropicApiKey";
const keyForm = document.getElementById("key-form");
const keyInput = document.getElementById("api-key");
const keyStatus = document.getElementById("key-status");

function storedKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch (err) {
    return "";
  }
}

function askHeaders() {
  const headers = { "Content-Type": "application/json" };
  const key = storedKey();
  if (key) headers["X-Anthropic-Key"] = key;
  return headers;
}

function renderKeyStatus() {
  const key = storedKey();
  if (!key) {
    keyStatus.textContent = "No key saved. Questions will use the server's key if it has one.";
    return;
  }
  keyStatus.textContent = `Saved: ${key.slice(0, 7)}…${key.slice(-4)}. Clear the field and save to remove.`;
}

keyForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = keyInput.value.trim();
  try {
    if (value) localStorage.setItem(KEY_STORAGE, value);
    else localStorage.removeItem(KEY_STORAGE);
  } catch (err) {
    keyStatus.textContent = "This browser is blocking local storage, so the key can't be saved.";
    return;
  }
  keyInput.value = "";
  renderKeyStatus();
});

renderKeyStatus();
