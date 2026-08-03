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

let currentConversationId = null;

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Minimal, fixed-format markdown renderer: this app only ever needs to
// render the research-note structure (## headings, - bullets, **bold**),
// not general markdown, so a small regex renderer is enough and avoids
// pulling in a dependency for a well-known, fixed output shape.
function renderMarkdown(text) {
  const lines = escapeHtml(text).split("\n");
  let html = "";
  let inList = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (line.startsWith("## ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h2>${line.slice(3)}</h2>`;
    } else if (line.startsWith("# ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h2>${line.slice(2)}</h2>`;
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inlineFormat(line.slice(2))}</li>`;
    } else if (line === "") {
      if (inList) { html += "</ul>"; inList = false; }
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<p>${inlineFormat(line)}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html;
}

function inlineFormat(line) {
  return line
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
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
  const div = document.createElement("div");
  div.className = "msg answer" + (blocked ? " blocked" : "");
  div.innerHTML = renderMarkdown(text);
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function loadPortfolio() {
  try {
    const res = await fetch("/api/portfolio");
    const data = await res.json();
    let rows = data.holdings
      .map((h) => {
        const plClass = h.unrealized_pl_pct >= 0 ? "pl-pos" : "pl-neg";
        const plPct = h.unrealized_pl_pct != null ? (h.unrealized_pl_pct * 100).toFixed(1) + "%" : "—";
        const weight = h.weight != null ? (h.weight * 100).toFixed(1) + "%" : "—";
        return `<tr><td>${h.ticker}</td><td class="num">${weight}</td><td class="num ${plClass}">${plPct}</td></tr>`;
      })
      .join("");
    portfolioEl.innerHTML = `<table>${rows}</table>`;
  } catch (err) {
    portfolioEl.textContent = "Could not load portfolio (is the backend running?)";
  }
}

// Small inline SVG sparkline — no charting library needed for a fixed,
// simple line-over-time shape like this.
function renderSparkline(points, isUp) {
  if (!points || points.length < 2) {
    return `<svg class="wl-spark" width="60" height="24"></svg>`;
  }
  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const w = 60, h = 24, pad = 2;
  const step = (w - pad * 2) / (closes.length - 1);
  const coords = closes.map((c, i) => {
    const x = pad + i * step;
    const y = h - pad - ((c - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = isUp ? "#59d99a" : "#ef6a6a";
  return `<svg class="wl-spark" width="${w}" height="${h}"><polyline points="${coords.join(" ")}" fill="none" stroke="${color}" stroke-width="1.5" /></svg>`;
}

async function loadWatchlist() {
  try {
    const res = await fetch("/api/watchlist");
    const items = await res.json();
    if (!items.length) {
      watchlistEl.innerHTML = `<div class="watchlist-error">No tickers yet — add one above.</div>`;
      return;
    }
    watchlistEl.innerHTML = items
      .map((item) => {
        const q = item.quote || {};
        if (q.error) {
          return `<div class="watchlist-row"><span class="wl-ticker">${item.ticker}</span><span class="wl-price">no data</span><button class="wl-remove" data-ticker="${item.ticker}">&times;</button></div>`;
        }
        const isUp = (q.change ?? 0) >= 0;
        const changePct = q.change_pct != null ? `${(q.change_pct * 100).toFixed(1)}%` : "—";
        const priceClass = isUp ? "pl-pos" : "pl-neg";
        return `<div class="watchlist-row">
          <span class="wl-ticker">${item.ticker}</span>
          ${renderSparkline(item.history, isUp)}
          <span class="wl-price ${priceClass}">$${q.price ?? "—"}<br>${changePct}</span>
          <button class="wl-remove" data-ticker="${item.ticker}" title="Remove">&times;</button>
        </div>`;
      })
      .join("");

    watchlistEl.querySelectorAll(".wl-remove").forEach((btn) => {
      btn.addEventListener("click", () => removeFromWatchlist(btn.dataset.ticker));
    });
  } catch (err) {
    watchlistEl.innerHTML = `<div class="watchlist-error">Could not load watchlist.</div>`;
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
      chatListEl.innerHTML = `<div class="watchlist-error">No chats yet.</div>`;
      return;
    }
    chatListEl.innerHTML = chats
      .map(
        (c) => `<div class="chat-item${c.id === currentConversationId ? " active" : ""}" data-id="${c.id}">
          <span class="chat-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)} &middot; ${relativeTime(c.updated_at)}</span>
          <button class="chat-remove" data-id="${c.id}" title="Delete chat">&times;</button>
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
    chatListEl.innerHTML = `<div class="watchlist-error">Could not load chats.</div>`;
  }
}

function clearLog() {
  log.innerHTML = "";
}

async function switchChat(id) {
  currentConversationId = id;
  clearLog();
  try {
    const res = await fetch(`/api/conversations/${id}`);
    if (!res.ok) throw new Error(`Backend returned ${res.status}`);
    const conversation = await res.json();
    if (!conversation.messages.length) {
      addMessage(
        "Ask a research question about your holdings or watchlist. Every answer is a research " +
          "note grounded in real metrics and filings — including a stated view when you ask for one.",
        "system"
      );
    }
    for (const m of conversation.messages) {
      if (m.role === "user") addMessage(m.text, "user");
      else addAnswer(m.text, false);
    }
  } catch (err) {
    addMessage(`Error loading chat: ${err.message}`, "system");
  }
  loadChatList();
}

async function createNewChat() {
  const res = await fetch("/api/conversations", { method: "POST" });
  const conversation = await res.json();
  currentConversationId = conversation.id;
  clearLog();
  addMessage(
    "Ask a research question about your holdings or watchlist. Every answer is a research " +
      "note grounded in real metrics and filings — including a stated view when you ask for one.",
    "system"
  );
  loadChatList();
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
  const res = await fetch("/api/conversations");
  const chats = await res.json();
  if (chats.length) {
    await switchChat(chats[0].id);
  } else {
    await createNewChat();
  }
}

newChatBtn.addEventListener("click", createNewChat);

async function ask(question) {
  if (!currentConversationId) {
    await createNewChat();
  }
  addMessage(question, "user");
  sendBtn.disabled = true;
  const loadingEl = addMessage("Researching…", "loading");

  try {
    const res = await fetch(`/api/conversations/${currentConversationId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    addMessage(`Error: ${err.message}`, "system");
  } finally {
    sendBtn.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;
  questionInput.value = "";
  ask(question);
});

questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll(".prompts li").forEach((li) => {
  li.addEventListener("click", () => {
    questionInput.value = li.dataset.prompt;
    form.requestSubmit();
  });
});

loadPortfolio();
loadWatchlist();
bootstrapChats();
