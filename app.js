const $ = (id) => document.getElementById(id);
const log = $("log"), chat = $("chat"), input = $("input"), sendBtn = $("send");
let busy = false, localInfo = { local: true, provider: "", model: "" };

/* ---------- small helpers ---------- */
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return res.json();
}
function store(key, value) { try { value === undefined ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch (e) {} }
function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("class", "i");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use"); u.setAttribute("href", "#i-" + name);
  s.appendChild(u); return s;
}
function mark() { return document.getElementById("kmark").content.firstElementChild.cloneNode(true); }
function nearBottom() { return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 140; }
const scrollBottomBtn = $("scrollBottom");
function updateScrollBtn() {
  if (!scrollBottomBtn) return;
  const isUp = chat.scrollHeight - chat.scrollTop - chat.clientHeight > 160;
  scrollBottomBtn.classList.toggle("visible", isUp);
}
chat.addEventListener("scroll", updateScrollBtn, { passive: true });
if (scrollBottomBtn) {
  scrollBottomBtn.onclick = () => {
    chat.scrollTo({ top: chat.scrollHeight, behavior: "smooth" });
    scrollBottomBtn.classList.remove("visible");
  };
}
function scrollDown(force) {
  if (force || nearBottom()) chat.scrollTop = chat.scrollHeight;
  updateScrollBtn();
}
function clock() { return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

/* ---------- theme and colour ---------- */
const THEMES = ["auto", "light", "dark"];
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  $("themeLabel").textContent = "Theme: " + t;
  $("themeUse").setAttribute("href", "#i-" + (t === "light" ? "sun" : t === "dark" ? "moon" : "auto"));
}
function applyAccent(a) {
  if (a && a !== "peacock") document.documentElement.dataset.accent = a; else delete document.documentElement.dataset.accent;
  const radio = document.querySelector('input[name="accent"][value="' + (a || "peacock") + '"]'); if (radio) radio.checked = true;
}
let theme = load("kai-theme") || "auto";
applyTheme(THEMES.includes(theme) ? theme : "auto");
applyAccent(load("kai-accent") || "peacock");
$("themeBtn").onclick = () => { theme = THEMES[(THEMES.indexOf(theme) + 1) % 3]; store("kai-theme", theme); applyTheme(theme); };
document.querySelectorAll('input[name="accent"]').forEach((r) => r.addEventListener("change", () => { store("kai-accent", r.value); applyAccent(r.value); }));
$("brandMark").appendChild(mark());

/* ---------- safe markdown (DOM nodes only, never innerHTML) ---------- */
const LATEX_MAP = {
  "\\approx": "≈", "\\times": "×", "\\cdot": "·", "\\pm": "±", "\\mp": "∓",
  "\\leq": "≤", "\\le": "≤", "\\geq": "≥", "\\ge": "≥", "\\neq": "≠",
  "\\equiv": "≡", "\\sim": "∼", "\\propto": "∝", "\\infty": "∞",
  "\\rightarrow": "→", "\\leftarrow": "←", "\\leftrightarrow": "↔", "\\to": "→",
  "\\partial": "∂", "\\nabla": "∇", "\\hbar": "ℏ",
  "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ",
  "\\epsilon": "ε", "\\zeta": "ζ", "\\eta": "η", "\\theta": "θ",
  "\\iota": "ι", "\\kappa": "κ", "\\lambda": "λ", "\\mu": "μ",
  "\\nu": "ν", "\\xi": "ξ", "\\pi": "π", "\\rho": "ρ",
  "\\sigma": "σ", "\\tau": "τ", "\\upsilon": "υ", "\\phi": "φ",
  "\\chi": "χ", "\\psi": "ψ", "\\omega": "ω",
  "\\Gamma": "Γ", "\\Delta": "Δ", "\\Theta": "Θ", "\\Lambda": "Λ",
  "\\Xi": "Ξ", "\\Pi": "Π", "\\Sigma": "Σ", "\\Phi": "Φ",
  "\\Psi": "Ψ", "\\Omega": "Ω",
  "\\quad": "  ", "\\qquad": "    ", "\\,": " ", "\\;": " "
};
function formatMath(parent, expr) {
  let s = (expr || "").trim();
  s = s.replace(/\\(text|mathrm|mathbf)\{([^}]+)\}/g, "$2");
  s = s.replace(/\\hat\{([^}]+)\}/g, "$1̂");
  s = s.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, "($1 / $2)");
  s = s.replace(/\\sqrt\{([^}]+)\}/g, "√($1)");
  s = s.replace(/\\(left|right)(?=[(\[|\]).|\s]|$)/g, "");
  for (const [k, v] of Object.entries(LATEX_MAP)) {
    if (s.includes(k)) s = s.split(k).join(v);
  }
  const SCRIPT_RE = /(\^\{([^}]+)\}|\^([A-Za-z0-9+-]))|(_\{([^}]+)\}|_([A-Za-z0-9+-]))/g;
  let last = 0, sm;
  while ((sm = SCRIPT_RE.exec(s)) !== null) {
    if (sm.index > last) parent.appendChild(document.createTextNode(s.slice(last, sm.index)));
    if (sm[1]) {
      const val = sm[2] !== undefined ? sm[2] : sm[3];
      parent.appendChild(el("sup", "", val));
    } else if (sm[4]) {
      const val = sm[5] !== undefined ? sm[5] : sm[6];
      parent.appendChild(el("sub", "", val));
    }
    last = sm.index + sm[0].length;
  }
  if (last < s.length) parent.appendChild(document.createTextNode(s.slice(last)));
}
const INLINE_RE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\\\([^\n]*?\\\))|(\[[^\]\n]+\]\(https?:\/\/[^)\s]+\))|(https?:\/\/[^\s<>"')\]]+[^\s<>"')\].,;:!?])/g;
function link(parent, href, label) {
  const a = el("a", "", label); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; parent.appendChild(a);
}
function inline(parent, text) {
  let last = 0, m; INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    parent.appendChild(document.createTextNode(text.slice(last, m.index)));
    const tok = m[0];
    if (m[1]) parent.appendChild(el("code", "", tok.slice(1, -1)));
    else if (m[2]) parent.appendChild(el("strong", "", tok.slice(2, -2)));
    else if (m[3]) { const span = el("span", "math-inline"); formatMath(span, tok.slice(2, -2)); parent.appendChild(span); }
    else if (m[4]) { const k = tok.indexOf("]("); link(parent, tok.slice(k + 2, -1), tok.slice(1, k)); }
    else link(parent, tok, tok);
    last = m.index + tok.length;
  }
  parent.appendChild(document.createTextNode(text.slice(last)));
}
function renderMd(root, text) {
  root.textContent = "";
  let para = null, list = null, code = null, sub = null, lastLi = null, mathBlock = null;
  const endList = () => { list = null; sub = null; lastLi = null; };
  for (const line of text.replace(/\s+$/, "").split("\n")) {
    if (code) { if (line.trim().startsWith("```")) code = null; else code.textContent += (code.textContent ? "\n" : "") + line; continue; }
    if (line.trim().startsWith("```")) {
      para = null; endList();
      const pre = el("pre"); code = el("code"); pre.appendChild(code); root.appendChild(pre); continue;
    }
    if (mathBlock !== null) {
      if (line.trim().endsWith("\\]") || line.trim().endsWith("$$")) {
        const part = line.trim().replace(/(\\\]|\$\$)$/, "").trim();
        if (part) mathBlock.push(part);
        para = null; endList();
        const div = el("div", "math-block"); formatMath(div, mathBlock.join(" ")); root.appendChild(div);
        mathBlock = null;
      } else {
        mathBlock.push(line.trim());
      }
      continue;
    }
    const tline = line.trim();
    if (!tline) { para = null; continue; }
    if (tline.startsWith("\\[") || tline.startsWith("$$")) {
      const closeTag = tline.startsWith("\\[") ? "\\]" : "$$";
      if (tline.length > 2 && tline.endsWith(closeTag)) {
        para = null; endList();
        const expr = tline.slice(2, -closeTag.length).trim();
        const div = el("div", "math-block"); formatMath(div, expr); root.appendChild(div);
        continue;
      }
      para = null; endList();
      const first = tline.slice(2).trim();
      mathBlock = first ? [first] : [];
      continue;
    }
    let m;
    if ((m = line.match(/^\s{0,3}#{1,4}\s+(.*)$/))) { para = null; endList(); const h = el("h4"); inline(h, m[1]); root.appendChild(h); continue; }
    if ((m = line.match(/^(\s*)([-*•]|\d+[.)])\s+(.*)$/))) {
      const indent = m[1].replace(/\t/g, "    ").length, ordered = /\d/.test(m[2]);
      if (list && lastLi && (indent >= 2 || (list.tagName === "OL" && !ordered))) {
        const want = ordered ? "OL" : "UL";
        if (!sub || sub.tagName !== want) { sub = el(want.toLowerCase()); lastLi.appendChild(sub); }
        const li = el("li"); inline(li, m[3]); sub.appendChild(li); continue;
      }
      if (!list || list.tagName !== (ordered ? "OL" : "UL")) { para = null; list = el(ordered ? "ol" : "ul"); root.appendChild(list); sub = null; }
      const li = el("li"); inline(li, m[3]); if (ordered) li.value = parseInt(m[2], 10);
      list.appendChild(li); lastLi = li; sub = null; continue;
    }
    endList();
    if (!para) { para = el("p"); root.appendChild(para); } else para.appendChild(el("br"));
    inline(para, line.trim());
  }
  if (mathBlock !== null && mathBlock.length > 0) {
    const div = el("div", "math-block"); formatMath(div, mathBlock.join(" ")); root.appendChild(div);
  }
}
function plainLinks(root, text) {
  root.textContent = ""; let last = 0, m; INLINE_RE.lastIndex = 0;
  const re = /https?:\/\/[^\s<>"')\]]+[^\s<>"')\].,;:!?]/g;
  while ((m = re.exec(text)) !== null) { root.appendChild(document.createTextNode(text.slice(last, m.index))); link(root, m[0], m[0]); last = m.index + m[0].length; }
  root.appendChild(document.createTextNode(text.slice(last)));
}
function fill(node, text) { node.dataset.raw = text; if (node.classList.contains("assistant")) renderMd(node, text); else plainLinks(node, text); }

/* ---------- conversation view ---------- */
function addUser(text) {
  const wrap = el("div", "user-wrap");
  const m = el("div", "msg user");
  fill(m, text);
  const acts = el("div", "acts");
  const copy = el("button", "btn ghost", "");
  copy.type = "button";
  copy.append(icon("copy"), document.createTextNode("Copy"));
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(text); } catch (e) {
      const t = el("textarea"); t.value = text; document.body.appendChild(t); t.select();
      try { document.execCommand("copy"); } catch (e2) {} t.remove();
    }
    copy.textContent = "";
    copy.append(icon("check"), document.createTextNode("Copied!"));
    copy.style.color = "var(--accent)";
    setTimeout(() => {
      copy.textContent = "";
      copy.append(icon("copy"), document.createTextNode("Copy"));
      copy.style.color = "";
    }, 1500);
  };
  acts.appendChild(copy);
  wrap.append(m, acts);
  log.appendChild(wrap);
  scrollDown(true);
  return m;
}
function addAssistant(text, when) {
  const row = el("div", "row"); const mk = el("span", "mark"); mk.appendChild(mark());
  const body = el("div", "body"); const msg = el("div", "msg assistant"); fill(msg, text);
  const acts = el("div", "acts");
  const copy = el("button", "btn ghost", ""); copy.type = "button"; copy.append(icon("copy"), document.createTextNode("Copy"));
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(msg.dataset.raw || msg.textContent || ""); } catch (e) {
      const t = el("textarea"); t.value = msg.dataset.raw || msg.textContent || ""; document.body.appendChild(t); t.select(); try { document.execCommand("copy"); } catch (e2) {} t.remove();
    }
    copy.textContent = "";
    copy.append(icon("check"), document.createTextNode("Copied!"));
    copy.style.color = "var(--accent)";
    setTimeout(() => {
      copy.textContent = "";
      copy.append(icon("copy"), document.createTextNode("Copy"));
      copy.style.color = "";
    }, 1500);
  };
  acts.appendChild(copy);
  if (when) acts.appendChild(el("span", "when", when));
  body.append(msg, acts); row.append(mk, body); log.appendChild(row);
  return msg;
}
function addNote(text, isError) { const c = el("div", "chip" + (isError ? " err" : ""), text); log.appendChild(c); scrollDown(true); }

const FRIENDLY = {
  get_current_time: "Checked the time", get_current_date: "Checked the date", calculate: "Did the maths",
  web_search: "Searched the web", web_fetch: "Read a web page", read_file: "Read a file", write_file: "Wrote a file",
  list_files: "Looked at files", remember: "Saved a memory", recall_memory: "Looked at memory",
};
function describeStep(text) {
  const m = text.match(/^Using tool (\w+)\(([\s\S]*)\)$/);
  if (!m) return null;
  let detail = "";
  try { detail = Object.entries(JSON.parse(m[2] || "{}")).filter(([, v]) => v !== "" && v !== null).map(([k, v]) => k + ": " + v).join(", "); } catch (e) { detail = m[2]; }
  return { label: FRIENDLY[m[1]] || m[1], detail };
}
let stepsBox = null;
function addStep(step) {
  if (!stepsBox) {
    stepsBox = el("details", "steps working"); stepsBox.dataset.n = "0";
    stepsBox.appendChild(el("summary")); stepsBox.appendChild(el("ul")); log.appendChild(stepsBox);
  }
  const n = +stepsBox.dataset.n + 1; stepsBox.dataset.n = n;
  const li = el("li"); li.append(el("b", "", step.label)); if (step.detail) li.append(document.createTextNode(" - " + step.detail));
  stepsBox.querySelector("ul").appendChild(li);
  stepsBox.querySelector("summary").textContent = "Working: " + step.label.toLowerCase() + (n > 1 ? " (" + n + " steps)" : "");
  scrollDown();
}
function finishSteps() {
  if (!stepsBox) return;
  const n = +stepsBox.dataset.n;
  stepsBox.classList.remove("working");
  stepsBox.querySelector("summary").textContent = "Used " + n + (n === 1 ? " tool" : " tools");
  stepsBox = null;
}

function markLast() {
  document.querySelectorAll(".row.last").forEach((r) => { r.classList.remove("last"); const b = r.querySelector(".retry"); if (b) b.remove(); });
  const rows = log.querySelectorAll(".row"); if (!rows.length) return;
  const last = rows[rows.length - 1];
  if (!log.querySelector(".msg.user")) return;
  last.classList.add("last");
  const retry = el("button", "btn ghost retry"); retry.type = "button"; retry.append(icon("retry"), document.createTextNode("Try again"));
  retry.onclick = () => regenerate();
  last.querySelector(".acts").appendChild(retry);
}

function clearChips() {
  const bar = $("chipsBar");
  if (bar) bar.textContent = "";
}

function showChips(lastUserMsg, lastAssistantReply) {
  const bar = $("chipsBar");
  if (!bar) return;
  bar.textContent = "";
  const reply = (lastAssistantReply || "").trim();
  const combined = (reply + " " + (lastUserMsg || "")).trim();
  if (!combined) return;

  const suggestions = [];

  // 1. Extract prominent topics from headings or bold titles
  const titles = reply.match(/(?:\d+\.\s*\*\*|###\s*|\*\*)([^\n*#:`]{4,35})(?:\*\*|:)/g);
  if (titles && titles.length) {
    const clean = titles[0].replace(/^[\d\.\s#\*]+|[\*\:\s]+$/g, "").trim();
    if (clean.length > 3 && !/^(example|note|tip|step)/i.test(clean)) {
      suggestions.push("Tell me more about " + clean);
    }
  }

  // 2. Science / Math / Physics
  if (/\b(quantum|physics|physic|equation|formula|math|calculus|particle|tunneling|atom|relativity|energy|wave)\b/i.test(combined)) {
    if (!suggestions.some((s) => s.includes("simpler"))) suggestions.push("Explain this in simpler terms");
    suggestions.push("What are practical applications of this?");
    suggestions.push("Give a step-by-step example");
  }
  // 3. Code / Tech / Programming
  else if (/```|\b(python|javascript|code|function|error|bug|api|database|sql|class|loop)\b/i.test(combined)) {
    suggestions.push("Show a working code example");
    suggestions.push("What are common mistakes or bugs here?");
    suggestions.push("How do I test this?");
  }
  // 4. Personal / Decisions / Relationships
  else if (/\b(breakup|relationship|feeling|feelings|advice|decide|decision|career|job|friend|grow|future)\b/i.test(combined)) {
    suggestions.push("Can you help me weigh pros and cons?");
    suggestions.push("What should my next step be?");
    suggestions.push("Give me another perspective on this");
  }
  // 5. General topics
  else {
    suggestions.push("Summarize this in 3 key points");
    suggestions.push("Tell me more details about this");
    suggestions.push("What should I ask next?");
  }

  const seen = new Set();
  const picked = [];
  for (const s of suggestions) {
    if (!seen.has(s)) {
      seen.add(s);
      picked.push(s);
    }
    if (picked.length >= 3) break;
  }

  picked.forEach((text) => {
    const btn = el("button", "chip-btn");
    btn.type = "button";
    const icon = el("span", "", "💡");
    icon.style.fontSize = "11px";
    btn.append(icon, document.createTextNode(text));
    btn.onclick = () => {
      clearChips();
      ask(text);
    };
    bar.appendChild(btn);
  });
}

function showEmpty(info) {
  clearChips();
  log.textContent = "";
  const box = el("div", "empty");
  const mk = el("span", "mark"); mk.appendChild(mark());
  box.appendChild(mk);
  box.appendChild(el("h2", "", "What shall we work on?"));
  box.appendChild(el("p", "", info.local
    ? "Runs on this computer with " + info.model + ". Only web searches and page reads go online."
    : "Uses the " + info.provider + " cloud with " + info.model + ", so your messages leave this computer."));
  const list = el("div", "starters");
  const items = [
    ["Ask about a document", "Attach a PDF or Word file", () => $("attach").click()],
    ["Search the web for the latest Android news", "Uses web search", () => ask("Search the web for the latest Android news")],
    ["What is the time in Tokyo?", "Uses the clock tool", () => ask("What is the time in Tokyo?")],
  ];
  items.forEach(([t, s, fn]) => {
    const b = el("button"); b.type = "button"; b.append(el("span", "", t), el("small", "", s)); b.onclick = fn; list.appendChild(b);
  });
  box.appendChild(list); log.appendChild(box);
}
function ask(text) { input.value = text; send(); }

function renderHistory(state) {
  clearChips();
  log.textContent = ""; stepsBox = null;
  if (!state.history.length) { showEmpty(localInfo); return; }
  state.history.forEach((m) => { if (m.role === "user") addUser(m.content); else addAssistant(m.content); });
  markLast(); scrollDown(true);
  const last = state.history[state.history.length - 1];
  if (last && last.role === "assistant") {
    const userTurn = state.history.slice(0, -1).reverse().find((m) => m.role === "user");
    showChips(userTurn ? userTurn.content : "", last.content);
  }
}

/* ---------- state, header, memory ---------- */
function setStatus(busyNow) {
  const box = $("status"); box.classList.toggle("busy", busyNow);
  $("statusText").textContent = busyNow ? "Thinking..." : (localInfo.local ? "On this computer - " : localInfo.provider + " cloud - ") + localInfo.model;
}
function render(state) {
  localInfo = { local: state.provider === "ollama", provider: state.provider, model: state.model };
  setStatus(busy);
  $("toolsBtn").setAttribute("aria-pressed", String(state.tools));
  $("toolsLabel").textContent = state.tools ? "Tools on" : "Tools off";
  const list = $("memList"); list.textContent = "";
  state.memories.forEach((fact, i) => {
    const li = el("li", "", fact + " "); const b = el("button", "", "remove"); b.type = "button";
    b.onclick = async () => render(await api("/api/memory", { action: "remove", index: i + 1 }));
    li.appendChild(b); list.appendChild(li);
  });
  $("memEmpty").style.display = state.memories.length ? "none" : "block";
  renderDocs(state);
  return state;
}
function setBusy(v) { busy = v; sendBtn.disabled = v; $("newBtn").disabled = v; $("stop").hidden = !v; setStatus(v); }
function stopStream() {
  try { window.speechSynthesis.cancel(); } catch (e) {}
  speakBuf = "";
  if (streamAbort) { try { streamAbort.abort(); } catch (e) {} }
}

/* ---------- approvals ---------- */
function askApproval(ev) {
  const card = el("div", "confirm"); card.setAttribute("role", "alertdialog");
  const p = el("p", "", ev.message); const btns = el("div", "btns");
  const yes = el("button", "btn primary", "Allow"), no = el("button", "btn", "Deny"); yes.type = no.type = "button";
  const answer = async (allow) => { yes.disabled = no.disabled = true; p.textContent += allow ? "\nAllowed." : "\nDenied."; await api("/api/confirm", { id: ev.id, allow }); };
  yes.onclick = () => answer(true); no.onclick = () => answer(false);
  btns.append(yes, no); card.append(p, btns); log.appendChild(card); scrollDown(true); no.focus();
}

/* ---------- streaming a reply ---------- */
let streamAbort = null;
async function stream(path, body) {
  setBusy(true); stepsBox = null; speakReset();
  streamAbort = new AbortController();
  let bubble = null, buffer = "", stopped = false, firstToken = true;
  bubble = addAssistant("", clock());
  const dots = el("span", "thinking-dots");
  dots.append(el("span"), el("span"), el("span"));
  bubble.appendChild(dots);
  bubble.classList.add("typing");
  scrollDown(true);
  try {
    const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: streamAbort.signal });
    if (!res.ok) {
      if (firstToken && bubble) { const row = bubble.closest(".row"); if (row) row.remove(); bubble = null; }
      const err = await res.json().catch(() => ({})); addNote("Error: " + (err.error || res.status), true); return;
    }
    const reader = res.body.getReader(), dec = new TextDecoder("utf-8"); let pending = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      pending += dec.decode(value, { stream: true }); let cut;
      while ((cut = pending.indexOf("\n\n")) >= 0) {
        const line = pending.slice(0, cut); pending = pending.slice(cut + 2);
        if (!line.startsWith("data: ")) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "token") {
          if (firstToken) {
            firstToken = false;
            bubble.textContent = "";
            finishSteps();
          }
          buffer += ev.text; const keep = nearBottom(); fill(bubble, buffer); if (keep) scrollDown(true); speakChunk(ev.text);
        } else if (ev.type === "event") {
          if (bubble && firstToken) {
            const row = bubble.closest(".row");
            if (row) row.remove();
            bubble = null;
            firstToken = true;
          } else if (bubble) {
            bubble.classList.remove("typing"); bubble = null; buffer = ""; speakFlush();
          }
          const step = describeStep(ev.text);
          if (step) addStep(step); else addNote(ev.text, false);
        } else if (ev.type === "confirm") { askApproval(ev);
        } else if (ev.type === "done") {
          if (firstToken && bubble) {
            bubble.textContent = "";
            firstToken = false;
          }
          if (!bubble && ev.reply) { finishSteps(); addAssistant(ev.reply, clock()); speakReply(ev.reply); } else speakFlush();
          showChips(lastPrompt, ev.reply || buffer);
        } else if (ev.type === "error") {
          if (firstToken && bubble) {
            const row = bubble.closest(".row");
            if (row) row.remove();
            bubble = null;
          }
          addNote("Error: " + ev.text, true);
        }
      }
    }
  } catch (e) {
    if (e && e.name === "AbortError") { stopped = true; }
    else {
      if (firstToken && bubble) {
        const row = bubble.closest(".row");
        if (row) row.remove();
        bubble = null;
      }
      addNote("Could not reach KAI (" + e.message + "). Is web_server.py still running?", true);
    }
  } finally {
    streamAbort = null;
    if (bubble) {
      bubble.classList.remove("typing");
      if (firstToken) {
        const row = bubble.closest(".row");
        if (row) row.remove();
      }
    }
    if (stopped) addNote("Stopped.", false);
    finishSteps(); setBusy(false); markLast(); input.focus(); refreshChats();
  }
}
$("stop").onclick = () => stopStream();
let lastPrompt = "";
async function send() {
  const text = input.value.trim(); if (!text || busy) return;
  lastPrompt = text;
  clearChips();
  input.value = ""; autosize();
  if (log.querySelector(".empty")) log.textContent = "";
  addUser(text); markLast(); await stream("/api/chat", { message: text });
}
async function regenerate() {
  if (busy) return;
  clearChips();
  const users = log.querySelectorAll(".msg.user"); if (!users.length) return;
  const lastWrap = users[users.length - 1].closest(".user-wrap") || users[users.length - 1];
  let node = lastWrap.nextSibling;
  while (node) { const next = node.nextSibling; node.remove(); node = next; }
  await stream("/api/regenerate", {});
}

/* ---------- documents ---------- */
function renderDocs(state) {
  const box = $("docs"); box.textContent = "";
  (state.docs || []).forEach((d) => {
    const chip = el("div", "doc"); const label = el("span", "", d.name); label.title = d.name + " (" + d.chars + " characters read)";
    const x = el("button", "", "×"); x.type = "button"; x.title = "Remove"; x.setAttribute("aria-label", "Remove " + d.name);
    x.onclick = async () => { const s = await api("/api/docs/remove", { name: d.name }); if (!s.error) renderDocs(s); else addNote("Error: " + s.error, true); };
    chip.append(label, x); box.appendChild(chip);
  });
}
$("attach").onclick = () => { if (!busy) $("file").click(); };
$("file").onchange = async () => {
  const file = $("file").files[0]; $("file").value = ""; if (!file) return;
  if (file.size > 5 * 1024 * 1024) { addNote("Error: file is too big (max 5 MB)", true); return; }
  const data = await new Promise((resolve, reject) => {
    const r = new FileReader(); r.onload = () => resolve(String(r.result).split(",")[1] || ""); r.onerror = () => reject(new Error("could not read the file")); r.readAsDataURL(file);
  }).catch((e) => { addNote("Error: " + e.message, true); return null; });
  if (data === null) return;
  if (log.querySelector(".empty")) log.textContent = "";
  setBusy(true); addNote("Reading " + file.name + "...", false);
  try {
    const s = await api("/api/upload", { name: file.name, data });
    if (s.error) addNote("Error: " + s.error, true); else { renderDocs(s); addNote("Attached " + file.name + ". Ask about it.", false); }
  } catch (e) { addNote("Upload failed: " + e.message, true); }
  finally { setBusy(false); input.focus(); }
};

/* ---------- saved chats ---------- */
function renderChats(info) {
  const list = $("chatList"); list.textContent = "";
  const active = info.chat_id || info.active; let title = "New chat";
  (info.chats || []).forEach((c) => {
    const li = el("li"); if (c.id === active) { li.className = "active"; title = c.title; }
    const open = el("button", "open", c.title); open.type = "button"; open.title = c.title;
    open.onclick = async () => {
      if (busy || c.id === active) return;
      const s = await api("/api/chat/open", { id: c.id });
      if (!s.error) { render(s); renderHistory(s); renderChats(s); closeSideOnMobile(); }
    };
    const del = el("button", "del", "×"); del.type = "button"; del.title = "Delete chat"; del.setAttribute("aria-label", "Delete chat " + c.title);
    del.onclick = async () => {
      if (busy || !confirm("Delete this chat?")) return;
      const s = await api("/api/chat/delete", { id: c.id });
      if (!s.error) { render(s); renderHistory(s); renderChats(s); }
    };
    li.append(open, del); list.appendChild(li);
  });
  $("chatTitle").textContent = title;
  $("chatEmpty").style.display = (info.chats || []).length ? "none" : "block";
}
async function refreshChats() { const info = await api("/api/chats", {}); if (!info.error) renderChats({ chats: info.chats, chat_id: info.active }); }
const isMobile = () => window.innerWidth <= 800;
function closeSideOnMobile() { if (isMobile()) { $("side").classList.remove("open"); syncScrim(); } }
function syncScrim() { $("scrim").classList.toggle("on", isMobile() && ($("side").classList.contains("open") || $("memory").classList.contains("open"))); }
$("menuBtn").onclick = () => { $("side").classList.toggle(isMobile() ? "open" : "collapsed"); syncScrim(); };
$("scrim").onclick = () => { $("side").classList.remove("open"); $("memory").classList.remove("open"); syncScrim(); };
const localBanner = $("localBanner");
if (localBanner && load("kai-banner-dismissed")) { localBanner.classList.add("hidden"); }
if ($("bannerClose")) {
  $("bannerClose").onclick = () => {
    if (localBanner) localBanner.classList.add("hidden");
    store("kai-banner-dismissed", "1");
  };
}
$("newBtn").onclick = async () => {
  let s = await api("/api/chat/new", {});
  if (s.error) s = await api("/api/clear", {});
  if (s.error) return;
  render(s); renderHistory(s); renderChats(s); closeSideOnMobile(); input.focus();
};

/* ---------- memory, tools, settings ---------- */
$("memBtn").onclick = () => { $("memory").classList.toggle("open"); closeSideOnMobile(); syncScrim(); };
$("toolsBtn").onclick = async () => { const on = $("toolsBtn").getAttribute("aria-pressed") === "true"; render(await api("/api/tools", { enabled: !on })); };
$("memInput").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter" || !$("memInput").value.trim()) return;
  const s = await api("/api/memory", { action: "add", text: $("memInput").value }); $("memInput").value = ""; render(s);
});
$("memClear").onclick = async () => { if (confirm("Delete all long-term memories?")) render(await api("/api/memory", { action: "clear" })); };

const dlg = $("settings");
function fillSettings(s) { $("sName").value = s.name; $("sRole").value = s.role || ""; $("sTone").value = s.tone || ""; $("sInstr").value = s.instructions || ""; }
function setMsg(t) { $("setMsg").textContent = t; }
$("setBtn").onclick = async () => {
  setMsg(""); fillSettings(await api("/api/state")); fillVoices();
  const info = await api("/api/models", {}); const sel = $("sModel"); sel.textContent = "";
  (info.models.length ? info.models : [info.current]).forEach((m) => { const o = el("option", "", m); o.value = m; if (m === info.current) o.selected = true; sel.appendChild(o); });
  sel.disabled = !info.can_switch;
  $("sModelNote").textContent = info.can_switch ? "Models installed in Ollama on this computer." : "Provider: " + info.provider + ". To change the model, edit MODEL_NAME in your .env file.";
  dlg.showModal();
};
$("sClose").onclick = () => dlg.close();
async function savePersona(extra) {
  const res = await api("/api/persona", Object.assign({ name: $("sName").value, role: $("sRole").value, tone: $("sTone").value, instructions: $("sInstr").value }, extra || {}));
  if (res.error) { setMsg(res.error); return null; }
  render(res); fillSettings(res); if (log.querySelector(".empty")) showEmpty(localInfo); return res;
}
$("setForm").addEventListener("submit", async (e) => {
  e.preventDefault(); if (!(await savePersona())) return;
  const sel = $("sModel");
  if (!sel.disabled) {
    const cur = (await api("/api/state")).model;
    if (sel.value && sel.value !== cur) { const res = await api("/api/model", { name: sel.value }); if (res.error) { setMsg(res.error); return; } render(res); }
  }
  setMsg("Saved."); setTimeout(() => dlg.close(), 500);
});
$("sReset").onclick = async () => { if (await savePersona({ reset: true })) setMsg("Persona reset to default."); };

/* ---------- browser voice (Web Speech API, no server needed) ---------- */
let speakOn = load("kai-speak") === "on";
function applySpeak() { $("speak").setAttribute("aria-pressed", String(speakOn)); }
let speakBuf = "";
let activeUtterances = 0;
function setSpeaking(active) {
  const btn = $("speak");
  if (btn) btn.classList.toggle("speaking", active);
}
function chosenVoice() {
  try {
    if (!("speechSynthesis" in window)) return null;
    const uri = load("kai-voice");
    if (!uri) return null;
    return window.speechSynthesis.getVoices().find((v) => v.voiceURI === uri) || null;
  } catch (e) { return null; }
}
function speakUtter(text) {
  try {
    const u = new SpeechSynthesisUtterance(String(text).slice(0, 500));
    u.rate = 1; u.volume = 0.9;
    const v = chosenVoice();
    if (v) u.voice = v;
    u.onstart = () => { activeUtterances++; setSpeaking(true); };
    u.onend = () => { activeUtterances = Math.max(0, activeUtterances - 1); if (!activeUtterances) setSpeaking(false); };
    u.onerror = () => { activeUtterances = Math.max(0, activeUtterances - 1); if (!activeUtterances) setSpeaking(false); };
    window.speechSynthesis.speak(u);
  } catch (e) {}
}
function fillVoices() {
  try {
    const sel = $("sVoice"); if (!sel) return;
    const voices = ("speechSynthesis" in window) ? window.speechSynthesis.getVoices() : [];
    const saved = load("kai-voice") || "";
    sel.textContent = "";
    const def = document.createElement("option"); def.value = ""; def.textContent = "Default (browser)"; sel.appendChild(def);
    const sorted = voices.slice().sort((a, b) => {
      const ae = a.lang.toLowerCase().startsWith("en") ? 0 : 1, be = b.lang.toLowerCase().startsWith("en") ? 0 : 1;
      return ae - be || a.name.localeCompare(b.name);
    });
    sorted.forEach((v) => {
      const o = document.createElement("option"); o.value = v.voiceURI; o.textContent = v.name + " (" + v.lang + ")";
      if (v.voiceURI === saved) o.selected = true;
      sel.appendChild(o);
    });
    if (saved && !sorted.some((v) => v.voiceURI === saved)) {
      const o = document.createElement("option"); o.value = saved; o.textContent = "Saved voice (not found)"; o.selected = true; sel.appendChild(o);
    }
    if (!voices.length) { const o = document.createElement("option"); o.value = ""; o.textContent = "No voices found in this browser"; sel.appendChild(o); }
  } catch (e) {}
}
function speakReset() { speakBuf = ""; activeUtterances = 0; setSpeaking(false); try { window.speechSynthesis.cancel(); } catch (e) {} }
function speakChunk(piece) {
  try {
    if (!speakOn || !piece || !("speechSynthesis" in window)) return;
    speakBuf += piece;
    for (;;) {
      const m = speakBuf.match(/^(.+?[.!?]+["']?\s|.+?\n)/);
      if (m && m[1].trim().length >= 3) { const s = m[1].trim(); speakBuf = speakBuf.slice(m[1].length); speakUtter(s); continue; }
      if (speakBuf.length > 280) {
        let cut = Math.max(speakBuf.lastIndexOf(" ", 280), 100);
        const s = speakBuf.slice(0, cut).trim(); speakBuf = speakBuf.slice(cut);
        if (s) speakUtter(s); else break;
      }
      break;
    }
  } catch (e) {}
}
function speakFlush() {
  try {
    if (!speakOn || !("speechSynthesis" in window)) { speakBuf = ""; return; }
    const s = speakBuf.trim(); speakBuf = "";
    if (s) speakUtter(s);
  } catch (e) { speakBuf = ""; }
}
function speakReply(text) { speakChunk(text || ""); speakFlush(); }
$("speak").onclick = () => { speakOn = !speakOn; store("kai-speak", speakOn ? "on" : "off"); applySpeak(); if (!speakOn) speakReset(); };
applySpeak();
$("sVoice").addEventListener("change", () => { store("kai-voice", $("sVoice").value || undefined); });
$("vTest").onclick = () => {
  store("kai-voice", $("sVoice").value || undefined);
  try { window.speechSynthesis.cancel(); } catch (e) {}
  const wasOn = speakOn; speakOn = true;
  speakUtter("Hello, I am " + ($("sName").value || "KAI") + ". This is my voice.");
  speakOn = wasOn;
};
try { if ("speechSynthesis" in window) window.speechSynthesis.onvoiceschanged = () => { if (dlg.open) fillVoices(); }; } catch (e) {}
(function setupMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const btn = $("mic");
  if (!SR) { btn.disabled = true; btn.title = "Voice input not supported in this browser (try Chrome or Edge)"; return; }
  btn.title = "Hold to talk, release to send. Or click for 10s listening.";
  let rec = null, finalText = "", downAt = 0, holding = false, touchEndAt = 0, listenTimer = 0;
  function clearListenTimer() { if (listenTimer) { clearTimeout(listenTimer); listenTimer = 0; } }
  function setLive(on, label) {
    btn.classList.toggle("live", on);
    btn.setAttribute("aria-pressed", String(on));
    btn.title = label || (on ? "Listening... click Stop to finish" : "Hold to talk, release to send. Or click for 10s listening.");
    btn.setAttribute("aria-label", label || (on ? "Stop listening" : "Speak instead of typing"));
  }
  function startRec() {
    if (busy || rec) return;
    finalText = "";
    rec = new SR(); rec.lang = "en-US"; rec.continuous = true; rec.interimResults = true; rec.maxAlternatives = 1;
    setLive(true, "Listening...");
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t + " ";
        else interim += t;
      }
      input.value = (finalText + interim).trim(); autosize();
    };
    rec.onerror = () => {};
    rec.onend = () => {
      clearListenTimer();
      const toSend = (finalText.trim() || input.value.trim());
      rec = null; setLive(false); holding = false; input.focus();
      if (toSend) { input.value = toSend; autosize(); send(); }
    };
    try { rec.start(); clearListenTimer(); listenTimer = setTimeout(() => { setLive(false); stopRec(); }, 10000); } catch (e) { rec = null; setLive(false); holding = false; clearListenTimer(); }
  }
  function stopRec() { clearListenTimer(); if (rec) { try { rec.stop(); } catch (e) { rec = null; setLive(false); holding = false; } } }
  btn.addEventListener("mousedown", (e) => { if (busy || rec) return; holding = true; downAt = Date.now(); startRec(); setLive(true, "Release to send"); });
  window.addEventListener("mouseup", () => {
    if (!holding || !rec) { holding = false; return; }
    holding = false;
    if (Date.now() - downAt < 300) { setLive(true, "Stop"); return; } // quick click = toggle mode
    setLive(false); stopRec();
  });
  btn.addEventListener("mouseleave", () => { if (holding && rec && Date.now() - downAt >= 300) { holding = false; setLive(false); stopRec(); } });
  btn.addEventListener("touchstart", (e) => { if (busy || rec) return; holding = true; downAt = Date.now(); startRec(); setLive(true, "Release to send"); e.preventDefault(); }, { passive: false });
  window.addEventListener("touchend", () => { if (!holding || !rec) return; holding = false; setLive(false); stopRec(); touchEndAt = Date.now(); });
  btn.onclick = () => { if (busy) return; if (Date.now() - touchEndAt < 600) return; if (rec && Date.now() - downAt < 600) return; if (rec) { holding = false; setLive(false); stopRec(); } else startRec(); };
})();

/* ---------- composer ---------- */
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; }
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
$("form").addEventListener("submit", (e) => { e.preventDefault(); send(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("memory").classList.remove("open"); closeSideOnMobile(); syncScrim(); } });

api("/api/state").then((s) => { render(s); renderHistory(s); refreshChats(); })
  .catch(() => { $("statusText").textContent = "server not reachable"; });
