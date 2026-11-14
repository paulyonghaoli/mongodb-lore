// Demo deck: arrow keys move between slides, live buttons open the real app above the deck.
// /demo is the 3-minute deck (slides marked data-short), /demo?1min the 1-minute one
// (data-1min), and /demo?full shows every slide.
const MODE = new URLSearchParams(location.search);
const PICK = MODE.has("full") ? () => true
  : MODE.has("1min") ? (s) => s.hasAttribute("data-1min")
  : (s) => s.hasAttribute("data-short");
const slides = [...document.querySelectorAll(".slide")].filter(PICK);
const LIMIT_S = MODE.has("full") ? 480 : MODE.has("1min") ? 60 : 180;
const overlay = document.getElementById("live");
const frame = document.getElementById("live-frame");
const progress = Object.assign(document.createElement("div"), { className: "progress" });
document.body.append(progress);
let current = 0;

// ---------- presenter timer: starts when you leave the first slide ----------
const timerEl = document.getElementById("timer");
let startedAt = null;
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
function tick() {
  const s = startedAt ? (Date.now() - startedAt) / 1000 : 0;
  timerEl.textContent = `${mmss(s)} / ${mmss(LIMIT_S)}`;
  timerEl.classList.toggle("near", s >= LIMIT_S - 30 && s < LIMIT_S);
  timerEl.classList.toggle("over", s >= LIMIT_S);
}
setInterval(tick, 500);
function resetTimer() { startedAt = null; tick(); }

function show(i) {
  current = Math.max(0, Math.min(slides.length - 1, i));
  if (current > 0 && startedAt === null) startedAt = Date.now();
  document.querySelectorAll(".slide").forEach((s) => s.classList.remove("active"));
  slides.forEach((s, n) => s.classList.toggle("active", n === current));
  document.getElementById("counter").textContent = `${current + 1} / ${slides.length}`;
  progress.style.width = `${((current + 1) / slides.length) * 100}%`;
  history.replaceState(null, "", `#${current + 1}`);
}

// ---------- live demo ----------
function openLive(button) {
  const { user = "fatima", tab = "analyst", q, run } = button.dataset;
  const params = new URLSearchParams({ user });
  if (q) params.set("q", q);
  if (q && run) params.set("run", run);
  const url = `/?${params}#${tab}`;
  // Reopening the same button shows the run already on screen (pre-run it before the talk);
  // only a different button loads, and so asks, again.
  if (frame.dataset.url !== url) { frame.dataset.url = url; frame.src = url; }
  const who = { fatima: "Fatima", alex: "Alex", sam: "Sam" }[user] || user;
  document.getElementById("live-title").textContent = `Live · ${who}${q ? ` · “${q}”` : ` · ${button.textContent.trim()}`}`;
  overlay.hidden = false;
  document.getElementById("live-close").focus();
}

function closeLive() {
  if (overlay.hidden) return;
  overlay.hidden = true;
  slides[current].querySelector(".live")?.focus({ preventScroll: true });
}

// Esc inside the app (same origin) also returns to the slides
frame.addEventListener("load", () => {
  try {
    frame.contentWindow.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !frame.contentDocument.querySelector("dialog[open]")) closeLive();
    });
  } catch { /* not same origin: the Back button still works */ }
});

// ---------- input ----------
document.addEventListener("click", (e) => {
  const live = e.target.closest(".live");
  if (live) openLive(live);
});
document.getElementById("prev").addEventListener("click", () => show(current - 1));
document.getElementById("next").addEventListener("click", () => show(current + 1));
document.getElementById("live-close").addEventListener("click", closeLive);

document.addEventListener("keydown", (e) => {
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  if (!overlay.hidden) { if (e.key === "Escape") closeLive(); return; }
  if (e.target.closest("button") && (e.key === " " || e.key === "Enter")) return; // let buttons click
  switch (e.key) {
    case "ArrowRight": case "PageDown": case " ": e.preventDefault(); show(current + 1); break;
    case "ArrowLeft": case "PageUp": e.preventDefault(); show(current - 1); break;
    case "Home": show(0); break;
    case "End": show(slides.length - 1); break;
    case "l": case "L": { const b = slides[current].querySelector(".live"); if (b) openLive(b); break; }
    case "r": case "R": resetTimer(); break;
    case "f": case "F":
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen?.().catch(() => {});
      break;
  }
});

const fromHash = () => (parseInt(location.hash.slice(1), 10) || 1) - 1;
window.addEventListener("hashchange", () => { if (fromHash() !== current) show(fromHash()); });
show(fromHash());
