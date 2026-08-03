Use the frontend-design skill to redesign the web frontend at web/ (index.html, style.css, app.js) for my project, an investment research copilot. The current version is plain and functional — dark background, monospace font, boxy panels — built for speed, not looks. I want a real visual identity now: something distinctive, confident, and good to look at, not a generic dark-mode chatbot skin.

What the product is: a personal, read-only research terminal for analyzing stocks — not a trading app, not a portfolio tracker with a chat bolted on. The user asks questions ("analyze my holdings," "what's your view on NVDA"), and gets back a structured research note: a metrics table, filing citations with real SEC source links, a risk list, and a stated view/rating grounded in that evidence. Think equity-research-analyst tool, not consumer fintech app. The subject matter — filings, ratios, citations, tickers, a ledger of research runs — has its own visual vocabulary (data density, tabular precision, provenance/sourcing) worth drawing from rather than defaulting to a generic AI-chat look.

Functional surface to preserve (backend is FastAPI, already built, do not change the API contracts):
- Chat: multiple named conversations, switchable, deletable, auto-expire after a week of inactivity. Currently a sidebar list above the portfolio panel.
- Portfolio panel: holdings with weight and unrealized P/L.
- Watchlist panel: tickers the user is tracking, each with live price, day change, and a small trend sparkline; add/remove ticker inline.
- Main chat log: user questions and assistant research notes, where each note has a fixed internal structure (Snapshot / Metrics table / Filing-backed observations with citations / Risks / Open questions / What would change my mind / View) — the design should make that structure scannable, not just render it as generic markdown.
- An input box to ask a new question, plus a few "quick prompt" suggestions.

Constraints: plain HTML/CSS/JS, no build step, no framework, no external font/icon CDN calls (self-contained). Must stay responsive down to mobile. Respect prefers-reduced-motion. This is a portfolio/demo project, so make a real aesthetic choice and commit to it — I'd rather have something opinionated than safe.

Follow the frontend-design skill's process: propose a token system (color, type, layout, one signature element) before writing code, sanity-check it isn't a generic default, then implement.
