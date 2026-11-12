"use strict";
const KEY = "tasklist_ak_v1";      // klucz localStorage (tylko gdy uruchomiono w zwykłej przeglądarce)
const DESKTOP = !!window.__DESKTOP__;
const HOUR = 48;                 // px na godzinę
const SNAP = 15;                 // minuty
const MONTHS = ["styczeń","luty","marzec","kwiecień","maj","czerwiec","lipiec","sierpień","wrzesień","październik","listopad","grudzień"];
const DOW = ["Pon","Wt","Śr","Czw","Pt","Sob","Nd"];


let tasks = [], people = [];
let filterPerson = "";           // "" = wszyscy, "__none" = nieprzypisane, inaczej id osoby
let listScope = "all", hideDone = false;
let view = "month", layout = "board";      // layout: tydzień/dzień jako kafelki (board) albo siatka godzinowa (grid)
let cur = new Date(); cur.setHours(0,0,0,0);
let drag = null;                 // {id, offY}
let started = false, readOnly = false, saveTimer = null, chain = Promise.resolve();
const api = () => window.pywebview && window.pywebview.api;
const errText = e => (e && (e.message || e.toString())) || "nieznany błąd";
function note(msg, ok){ const el = document.getElementById("note"); el.textContent = msg || ""; el.hidden = !msg; el.classList.toggle("ok", !!ok); }
let fileInfo = null, saveErr = false;     // zapamiętany plik Excela: {name, path, dirty}
function showFile(){
  const el = document.getElementById("fileTag"), sb = document.getElementById("saveBtn");
  if(sb){                                           // ikona „Zapisz”: do zapamiętanego pliku Excela (bez pliku: pyta o nazwę)
    sb.classList.toggle("dirty", !!(fileInfo && fileInfo.dirty));
    sb.title = fileInfo ? `Zapisz do pliku Excela: ${fileInfo.name} (Ctrl+S)${fileInfo.dirty ? " — są niezapisane zmiany" : ""}` : "Zapisz do pliku Excela… (wybierz plik, Ctrl+S)";
  }
  if(!DESKTOP || !fileInfo){ el.hidden = true; return; }
  el.hidden = false; el.title = fileInfo.path;
  el.textContent = "📄 " + fileInfo.name + (fileInfo.dirty ? " ● niezapisane zmiany" : " ✓");
  el.classList.toggle("dirty", !!fileInfo.dirty);
}

/* ---- zapis: w aplikacji do pliku w %LOCALAPPDATA%\TaskListAK, w przeglądarce do localStorage ---- */
const currentData = () => ({people, tasks});
/* ---- status zadania: oczekujące (domyślny) / w trakcie / zrobione + postęp 0–100 co 25 ---- */
const STATUS = {
  pending:  {icon: "⚪", label: "Oczekujące"},
  progress: {icon: "🔄", label: "W trakcie"},
  done:     {icon: "✅", label: "Zrobione"}
};
const STEPS = [0, 25, 50, 75, 100];
/* ---- kolor zadania: domyślnie wg priorytetu, można wybrać własny ---- */
const PALETTE = ["#d9453d", "#e8833a", "#e0a100", "#2e9e5b", "#1fa5a0", "#3b6cf6", "#6b5be6", "#a855c7", "#e0529c", "#7a8499"];
const colorStyle = t => t.color ? `--tc:${t.color};` : "";
function applyStatus(t, s){        // zrobione = 100%, oczekujące = 0%
  t.status = s;
  if(s === "done") t.progress = 100;
  else if(s === "pending") t.progress = 0;
  else if(t.progress === 0) t.progress = 25;
  else if(t.progress === 100) t.progress = 50;
}
function applyProgress(t, p){      // 100% = zrobione; postęp > 0 = w trakcie
  t.progress = p;
  if(p === 100) t.status = "done";
  else if(t.status === "done") t.status = p > 0 ? "progress" : "pending";
  else if(p > 0) t.status = "progress";
}
function fixTask(t){               // wersje < 1.2 miały tylko pole done
  const o = Object.assign({assignees: []}, t);
  o.status = STATUS[o.status] ? o.status : (o.done ? "done" : "pending");
  delete o.done;
  if(!o.end_date || o.end_date < o.date) o.end_date = o.date;       // zadanie wielodniowe: end_date > date
  if(o.end_date > o.date){ o.start = ""; o.end = ""; }
  o.series = typeof o.series === "string" ? o.series : "";
  o.color = /^#[0-9a-fA-F]{6}$/.test(o.color || "") ? o.color.toLowerCase() : "";   // pusty = kolor wg priorytetu
  if(o.status === "done") o.progress = 100; else if(!STEPS.includes(o.progress)) o.progress = 0;
  return o;
}
function normalize(d){        // akceptuje stary format (sama lista zadań z wersji 1.0)
  if(Array.isArray(d)) d = {people: [], tasks: d};
  if(!d || !Array.isArray(d.tasks)) throw new Error("Nieprawidłowy format danych.");
  const ppl = Array.isArray(d.people) ? d.people : [];
  return {people: ppl, tasks: d.tasks.map(fixTask)};
}
function save(){
  if(!DESKTOP){ try{ localStorage.setItem(KEY, JSON.stringify(currentData())); }catch(e){} return; }
  if(readOnly) return;
  clearTimeout(saveTimer); saveTimer = setTimeout(flush, 150);
}
function flush(){
  clearTimeout(saveTimer);
  if(!DESKTOP || readOnly) return chain;
  const snap = JSON.parse(JSON.stringify(currentData()));
  chain = chain.then(() => api().save_data(snap)).then(res => {
    if(fileInfo && res && typeof res === "object"){ fileInfo.dirty = !!res.dirty; showFile(); }
    if(saveErr){ saveErr = false; note(""); }
  }).catch(e => { saveErr = true; note("Zapis nie powiódł się: " + errText(e)); });
  return chain;
}
let savedView = null;
function saveView(){
  if(view === savedView) return; savedView = view;
  if(DESKTOP){ if(api()) api().set_view(view).catch(() => {}); }
  else { try{ localStorage.setItem(KEY + "_view", view); }catch(e){} }
}
/* ---- motyw jasny / ciemny: wybór użytkownika ma pierwszeństwo, bez wyboru obowiązuje motyw systemu ---- */
let theme = "";                                  // "" = wg systemu, "light" lub "dark"
const systemDark = () => !!(window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
const effectiveTheme = () => theme || (systemDark() ? "dark" : "light");
function applyTheme(){
  if(theme) document.documentElement.setAttribute("data-theme", theme); else document.documentElement.removeAttribute("data-theme");
  document.querySelectorAll("#themeSeg .btn").forEach(b => b.classList.toggle("active", b.dataset.t === effectiveTheme()));
}
function saveTheme(){
  if(DESKTOP){ if(api()) api().set_theme(theme).catch(() => {}); }
  else { try{ localStorage.setItem(KEY + "_theme", theme); }catch(e){} }
}
let savedLayout = null;
function saveLayout(){
  if(layout === savedLayout) return; savedLayout = layout;
  if(DESKTOP){ if(api()) api().set_layout(layout).catch(() => {}); }
  else { try{ localStorage.setItem(KEY + "_layout", layout); }catch(e){} }
}
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2,6);
const pad = n => String(n).padStart(2,"0");
const iso = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
const parse = s => { const [y,m,d] = s.split("-").map(Number); return new Date(y,m-1,d); };
const addDays = (d,n) => { const x = new Date(d); x.setDate(x.getDate()+n); return x; };
const mondayOf = d => addDays(d, -((d.getDay()+6)%7));
const toMin = t => { const [h,m] = t.split(":").map(Number); return h*60+m; };
const toHM = m => { m = Math.max(0, Math.min(1440, m)); return `${pad(Math.floor(m/60)%24)}:${pad(m%60)}`; };
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const byTime = (a,b) => (a.start||"").localeCompare(b.start||"") || a.title.localeCompare(b.title);
const personName = id => { const p = people.find(x => x.id === id); return p ? p.name : ""; };
const namesOf = t => (t.assignees || []).map(personName).filter(Boolean);
const sortedPeople = () => [...people].sort((a, b) => a.name.localeCompare(b.name, "pl"));
// osoby zapisujemy jako „Nazwisko Imię”; na kafelkach skrót: „Nazwisko I.”
const shortName = n => { const w = n.split(/\s+/).filter(Boolean); return w.length > 1 ? w[0] + " " + w[1][0].toUpperCase() + "." : (w[0] || ""); };
const matchesFilter = t => !filterPerson || (filterPerson === "__none" ? !(t.assignees||[]).length : (t.assignees||[]).includes(filterPerson));
const visibleTasks = () => tasks.filter(matchesFilter);
/* ---- zadania wielodniowe i przesuwanie ---- */
const endOf = t => t.end_date || t.date;
const isMulti = t => endOf(t) > t.date;
const occursOn = (t, ds) => t.date <= ds && ds <= endOf(t);
const dayNum = s => { const [y, m, d] = s.split("-").map(Number); return Date.UTC(y, m - 1, d) / 864e5; };
const daysBetween = (a, b) => Math.round(dayNum(b) - dayNum(a));
function shiftBy(t, n){ t.date = iso(addDays(parse(t.date), n)); t.end_date = iso(addDays(parse(endOf(t)), n)); }
const moveToDate = (t, ds) => shiftBy(t, daysBetween(t.date, ds));
// w komórce dnia: najpierw zadania wielodniowe (stała kolejność, by paski się wyrównywały), potem wg godziny
const daySort = (a, b) => (isMulti(b) - isMulti(a)) || (isMulti(a) && (a.date.localeCompare(b.date) || a.id.localeCompare(b.id))) || byTime(a, b);
const tasksOn = ds => visibleTasks().filter(t => occursOn(t, ds)).sort(daySort);

/* ================= render ================= */
function renderCal(){
  const cal = document.getElementById("cal");
  if(view === "month") renderMonth(cal);                    // miesiąc: zawsze klasyczny kalendarz
  else if(layout === "board") renderBoard(cal);
  else renderTimeGrid(cal, view === "week");
}
function render(){
  hideTip();
  document.querySelectorAll("#views .btn").forEach(b => b.classList.toggle("active", b.dataset.v === view));
  layoutSeg.hidden = false;                                  // „Kafelki / Siatka” dla miesiąca, tygodnia i dnia
  applyTheme();
  document.querySelectorAll("#layoutSeg .btn").forEach(b => b.classList.toggle("active", b.dataset.l === layout));
  fillPersonFilter();
  renderCal();
  renderList();
  saveView(); saveLayout();
}

function setTitle(s){ document.getElementById("title").textContent = s; }

// ds = dzień, w którego komórce rysujemy kafelek (zadania wielodniowe łączą się między dniami)
function chipHTML(t, ds){
  const multi = isMulti(t), end = endOf(t), dow = ds ? (parse(ds).getDay() + 6) % 7 : 0;
  const lj = multi && ds && ds !== t.date && dow !== 0;          // połączony z poprzednim dniem
  const rj = multi && ds && ds !== end && dow !== 6;             // połączony z następnym dniem
  const time = t.start ? t.start + " " : "";
  const names = namesOf(t), who = names.length ? ` <span class="who">· ${esc(names.map(shortName).join(", "))}</span>` : "";
  const tip = esc(t.title) + (names.length ? " — " + esc(names.join(", ")) : "") + (multi ? ` (${fmtShort(t)})` : "") + (t.series ? " 🔁" : "");
  let pg = t.progress;                                            // postęp rozłożony na wszystkie dni zadania
  if(multi && ds){ const n = daysBetween(t.date, end) + 1, i = daysBetween(t.date, ds); pg = Math.round(Math.min(1, Math.max(0, (t.progress / 100 - i / n) * n)) * 100); }
  const label = lj ? "&nbsp;" : `${stIcon(t)}${t.series ? '<span class="sti">🔁</span>' : ""}${time}${esc(t.title)}${who}`;
  const handle = ds && ds === end ? `<span class="rzd" data-rzd="${t.id}" title="Przeciągnij, aby zmienić liczbę dni"></span>` : "";
  return `<span class="chip p${t.priority} st-${t.status}${lj ? " lj" : ""}${rj ? " rj" : ""}" style="${colorStyle(t)}--pg:${pg}%" draggable="true" data-id="${t.id}">${label}${handle}</span>`;
}
const stIcon = t => t.status === "pending" ? "" : `<span class="sti">${STATUS[t.status].icon}</span>`;

function fillPersonFilter(){
  const sel = document.getElementById("fPerson");
  if(filterPerson && filterPerson !== "__none" && !people.some(p => p.id === filterPerson)) filterPerson = "";
  sel.innerHTML = `<option value="">Wszystkie osoby</option><option value="__none">Nieprzypisane</option>` +
    sortedPeople().map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
  sel.value = filterPerson;
}

function renderMonth(main){
  setTitle(`${MONTHS[cur.getMonth()]} ${cur.getFullYear()}`);
  const first = new Date(cur.getFullYear(), cur.getMonth(), 1);
  const start = mondayOf(first);
  const todayS = iso(new Date());
  const tiles = layout === "board";                                  // miesiąc jako kalendarz: zadania jako chipy (siatka) albo karty (kafelki)
  let h = `<div class="month${tiles ? " tiles" : ""}">` + DOW.map(d => `<div class="dow">${d}</div>`).join("");
  for(let i=0;i<42;i++){
    const d = addDays(start,i), ds = iso(d);
    const cls = ["cell", d.getMonth()!==cur.getMonth()?"other":"", d.getDay()%6===0?"weekend":"", ds===todayS?"today":""].join(" ");
    h += `<div class="${cls}" data-date="${ds}"><span class="daynum" data-goto="${ds}">${d.getDate()}</span>` +
         (tiles ? tasksOn(ds).sort((a, b) => (a.status === "done") - (b.status === "done")).map(t => cardHTML(t, ds, false, true)).join("")
                : tasksOn(ds).map(t => chipHTML(t, ds)).join("")) + `</div>`;
  }
  main.innerHTML = h + "</div>";

  main.querySelectorAll(".cell").forEach(c => {
    c.addEventListener("dblclick", e => { if(!e.target.closest(".chip")) openDialog(null, c.dataset.date); });
    c.addEventListener("dragover", e => { if(drag || ext(e)){ e.preventDefault(); c.classList.add("over"); } });
    c.addEventListener("dragleave", () => c.classList.remove("over"));
    c.addEventListener("drop", e => {
      e.preventDefault(); c.classList.remove("over");
      if(drag){ const t = byId(drag.id); if(t){ shiftBy(t, daysBetween(drag.grab, c.dataset.date)); save(); render(); } }
      else if(ext(e)) handleMailDrop(e.dataTransfer, c.dataset.date);
    });
  });
  bindChips(main);
  bindSpanHandles(main);
  if(tiles) bindChecks(main);
  main.querySelectorAll("[data-goto]").forEach(s => s.onclick = () => { cur = parse(s.dataset.goto); view = "day"; render(); });
}

function bindChips(root){
  root.querySelectorAll("[data-id]").forEach(el => {
    el.addEventListener("dragstart", e => {
      const r = el.getBoundingClientRect();
      const t = byId(el.dataset.id), holder = el.closest("[data-date]");      // dzień, w którym chwycono kafelek
      drag = { id: el.dataset.id, offY: e.clientY - r.top, grab: (holder && holder.dataset.date) || (t && t.date) };
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", el.dataset.id);
      setTimeout(() => el.classList.add("dragging"), 0);
    });
    el.addEventListener("dragend", () => { drag = null; el.classList.remove("dragging"); });
    el.addEventListener("click", e => { e.stopPropagation(); openDialog(el.dataset.id); });
  });
}

// rozciąganie zadania na kolejne dni: przeciągnij prawą krawędź kafelka (miesiąc, pasek „cały dzień”)
function bindSpanHandles(root){
  root.querySelectorAll("[data-rzd]").forEach(h => { h.addEventListener("click", e => e.stopPropagation()); h.addEventListener("mousedown", e => {
    e.preventDefault(); e.stopPropagation();
    const t = byId(h.dataset.rzd); if(!t) return;
    h.parentElement.draggable = false;
    let target = endOf(t);
    const cells = () => root.querySelectorAll(".cell[data-date], .allday[data-date]");
    const move = m => {
      const el = document.elementFromPoint(m.clientX, m.clientY), c = el && el.closest(".cell[data-date], .allday[data-date]");
      if(!c) return;
      target = c.dataset.date < t.date ? t.date : c.dataset.date;
      cells().forEach(x => x.classList.toggle("resz", x.dataset.date >= t.date && x.dataset.date <= target));
    };
    const up = () => {
      document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up);
      cells().forEach(x => x.classList.remove("resz"));
      if(target !== endOf(t)){
        if(target > t.date && t.start && !confirm("Zadanie wielodniowe jest całodniowe — godziny zostaną usunięte. Kontynuować?")){ render(); return; }
        t.end_date = target;
        if(target > t.date){ t.start = ""; t.end = ""; }
        save(); note("");
      }
      render();
    };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  }); });
}

/* ---- week / day ---- */
function layoutDay(list){
  // układ nakładających się zadań w kolumnach
  const evs = list.map(t => ({t, s: toMin(t.start), e: Math.max(toMin(t.start)+30, t.end ? toMin(t.end) : toMin(t.start)+60)}))
                  .sort((a,b) => a.s - b.s || a.e - b.e);
  const groups = []; let g = null, gEnd = -1;
  for(const ev of evs){
    if(!g || ev.s >= gEnd){ g = []; groups.push(g); gEnd = ev.e; } else gEnd = Math.max(gEnd, ev.e);
    g.push(ev);
  }
  for(const grp of groups){
    const cols = [];
    for(const ev of grp){
      let c = cols.findIndex(end => end <= ev.s);
      if(c < 0){ c = cols.length; cols.push(0); }
      cols[c] = ev.e; ev.c = c;
    }
    grp.forEach(ev => ev.n = cols.length);
  }
  return evs;
}

/* ================= widok kafelkowy (tydzień / dzień): kolumna „Zaległe” + kolumny dni z kartami ================= */
const MONTHS_SHORT = ["sty","lut","mar","kwi","maj","cze","lip","sie","wrz","paź","lis","gru"];
const WEEKDAYS = ["Niedziela","Poniedziałek","Wtorek","Środa","Czwartek","Piątek","Sobota"];
let boardAdd = null;                    // dzień, w którym otwarty jest formularz szybkiego dodawania
const shortDate = ds => { const d = parse(ds); return `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`; };

// kółko na karcie: zrobione ↔ oczekujące
function bindChecks(root){
  root.querySelectorAll("[data-check]").forEach(b => {
    b.addEventListener("click", e => {
      e.stopPropagation();
      const t = byId(b.dataset.check); if(!t) return;
      applyStatus(t, t.status === "done" ? "pending" : "done"); save(); render();
    });
    b.addEventListener("mousedown", e => e.stopPropagation());
  });
}
function cardHTML(t, ds, overdue, compact){
  const names = namesOf(t), multi = isMulti(t);
  const note = compact ? "" : ((t.notes || "").split(String.fromCharCode(10)).find(l => l.trim()) || "").trim();
  const meta = [];
  if(overdue) meta.push(`<span class="late">📅 ${shortDate(t.date)}</span>`);
  if(t.start) meta.push(`<span>🕒 ${t.start}${t.end ? "–" + t.end : ""}</span>`);
  if(multi && ds) meta.push(`<span>📅 dzień ${daysBetween(t.date, ds) + 1}/${daysBetween(t.date, endOf(t)) + 1}</span>`);
  if(names.length) meta.push(`<span title="${esc(names.join(", "))}">👥 ${esc(names.map(shortName).join(", "))}</span>`);
  if(t.series) meta.push(`<span title="Zadanie cykliczne">🔁</span>`);
  if(t.status === "progress") meta.push(`<span>🔄 ${t.progress}%</span>`);
  return `<article class="card p${t.priority} st-${t.status}" style="${colorStyle(t)}--pg:${t.progress}%" draggable="true" data-id="${esc(t.id)}">` +
    `<button class="ccheck" type="button" data-check="${esc(t.id)}" title="${t.status === "done" ? "Cofnij (oczekujące)" : "Oznacz jako zrobione"}">${t.status === "done" ? "✓" : ""}</button>` +
    `<div class="cbody"><div class="ctitle">${esc(t.title)}</div>${note ? `<div class="cnote">${esc(note.slice(0, 120))}</div>` : ""}` +
    (meta.length ? `<div class="cmeta">${meta.join("")}</div>` : "") + `</div></article>`;
}

function dayLabel(d, todayS){
  const ds = iso(d), tomorrow = iso(addDays(new Date(), 1));
  const name = ds === todayS ? "Dziś" : ds === tomorrow ? "Jutro" : WEEKDAYS[d.getDay()];
  return `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]} · ${name}`;
}

let boardKey = "", boardScrollX = 0;      // zapamiętane przewinięcie poziome (miesiąc: 30 kolumn)
function renderBoard(main){
  let days;
  if(view === "month"){
    const n = new Date(cur.getFullYear(), cur.getMonth() + 1, 0).getDate();
    days = Array.from({length: n}, (_, i) => new Date(cur.getFullYear(), cur.getMonth(), i + 1));
    setTitle(`${MONTHS[cur.getMonth()]} ${cur.getFullYear()}`);
  } else if(view === "week"){
    days = Array.from({length: 7}, (_, i) => addDays(mondayOf(cur), i));
    const a = days[0], b = days[6];
    setTitle(`${a.getDate()} ${MONTHS[a.getMonth()].slice(0,3)} – ${b.getDate()} ${MONTHS[b.getMonth()].slice(0,3)} ${b.getFullYear()}`);
  } else {
    days = [new Date(cur)];
    setTitle(`${DOW[(cur.getDay()+6)%7]}, ${cur.getDate()} ${MONTHS[cur.getMonth()]} ${cur.getFullYear()}`);
  }
  const key = view + iso(days[0]), oldBoard = main.querySelector(".board");
  if(oldBoard && key === boardKey) boardScrollX = oldBoard.scrollLeft;

  const todayS = iso(new Date());
  const overdue = visibleTasks().filter(t => t.status !== "done" && endOf(t) < todayS).sort(byDue);
  let h = `<div class="board${view === "month" ? " bmonth" : ""}">`;
  h += `<section class="bcol bover"><header><b>Zaległe</b><span class="bcount">${overdue.length}</span>` +
       (overdue.length ? `<button class="blink" id="bResched" type="button">Zmień termin</button>` : "") + `</header>` +
       `<div class="bcards">${overdue.map(t => cardHTML(t, null, true)).join("") || `<div class="bempty">Brak zaległych zadań 🎉</div>`}</div></section>`;
  for(const d of days){
    const ds = iso(d);
    const list = tasksOn(ds).sort((a, b) => (a.status === "done") - (b.status === "done"));   // zrobione na dole
    h += `<section class="bcol${ds === todayS ? " today" : ""}${d.getDay() % 6 === 0 ? " weekend" : ""}" data-date="${ds}"><header><b>${dayLabel(d, todayS)}</b><span class="bcount">${list.length}</span></header>` +
         `<div class="bcards">${list.map(t => cardHTML(t, ds, false)).join("")}</div>` +
         `<div class="badd" data-add="${ds}"><button class="bplus" type="button">＋ Dodaj zadanie</button></div></section>`;
  }
  main.innerHTML = h + `</div>`;
  const board = main.querySelector(".board");
  if(key === boardKey) board.scrollLeft = boardScrollX;                    // ta sama strona: zachowaj przewinięcie
  else {                                                                   // nowy okres: w miesiącu przewiń do dzisiaj
    boardKey = key; boardScrollX = 0;
    const t = board.querySelector(".bcol.today");
    if(t && view === "month") board.scrollLeft = Math.max(0, t.offsetLeft - board.querySelector(".bover").offsetWidth - 32);
  }

  // przeciąganie kart między dniami
  main.querySelectorAll(".bcol[data-date]").forEach(c => {
    c.addEventListener("dragover", e => { if(drag || ext(e)){ e.preventDefault(); c.classList.add("over"); } });
    c.addEventListener("dragleave", e => { if(!c.contains(e.relatedTarget)) c.classList.remove("over"); });
    c.addEventListener("drop", e => {
      e.preventDefault(); c.classList.remove("over");
      if(drag){ const t = byId(drag.id); if(t){ shiftBy(t, daysBetween(drag.grab, c.dataset.date)); save(); render(); } }
      else if(ext(e)) handleMailDrop(e.dataTransfer, c.dataset.date);
    });
  });
  bindChips(main);
  bindChecks(main);
  // „Zmień termin” dla zaległych
  const rs = main.querySelector("#bResched");
  if(rs) rs.onclick = e => {
    e.stopPropagation();
    const r = rs.getBoundingClientRect();
    ctx.innerHTML = `<button type="button" class="ctx-item" data-od="today">📅 Przenieś zaległe na dziś</button>` +
                    `<button type="button" class="ctx-item" data-od="overdueNext">➡ Przenieś zaległe na przyszły tydzień</button>`;
    ctx.hidden = false;
    ctx.style.left = Math.max(4, Math.min(r.left, innerWidth - 270)) + "px"; ctx.style.top = (r.bottom + 4) + "px";
    ctx.querySelectorAll("[data-od]").forEach(x => x.onclick = () => { hideCtx(); bulkMove(x.dataset.od); });
  };
  // szybkie dodawanie zadania w kolumnie dnia
  main.querySelectorAll(".badd").forEach(box => {
    const ds = box.dataset.add;
    const closeForm = () => { boardAdd = null; box.innerHTML = `<button class="bplus" type="button">＋ Dodaj zadanie</button>`; box.querySelector(".bplus").onclick = openForm; };
    function openForm(){
      boardAdd = ds;
      box.innerHTML = `<div class="bform"><input type="text" class="binp" placeholder="Nazwa zadania" maxlength="300" autocomplete="off">` +
        `<div class="brow"><button type="button" class="btn primary bok">Dodaj</button><button type="button" class="btn bmore">Szczegóły…</button><button type="button" class="btn bno">Anuluj</button></div></div>`;
      const inp = box.querySelector(".binp");
      const add = () => {
        const title = inp.value.trim(); if(!title){ inp.focus(); return; }
        const preset = (filterPerson && filterPerson !== "__none") ? [filterPerson] : [];
        tasks.push({id: uid(), title, date: ds, end_date: ds, start: "", end: "", priority: 1, status: "pending", progress: 0, notes: "", assignees: preset, series: ""});
        save(); render();                                    // formularz otworzy się ponownie (boardAdd) — kolejne zadanie
      };
      box.querySelector(".bok").onclick = add;
      box.querySelector(".bmore").onclick = () => { const title = inp.value.trim(); closeForm(); openDialog(null, ds, "", {title}); };
      box.querySelector(".bno").onclick = closeForm;
      inp.addEventListener("keydown", e => { if(e.key === "Enter"){ e.preventDefault(); add(); } else if(e.key === "Escape"){ e.preventDefault(); closeForm(); } e.stopPropagation(); });
      inp.focus();
    }
    box.querySelector(".bplus").onclick = openForm;
    if(boardAdd === ds) openForm();
  });
}

function renderTimeGrid(main, isWeek){
  const days = isWeek ? Array.from({length:7}, (_,i) => addDays(mondayOf(cur), i)) : [new Date(cur)];
  if(isWeek){ const a = days[0], b = days[6];
    setTitle(`${a.getDate()} ${MONTHS[a.getMonth()].slice(0,3)} – ${b.getDate()} ${MONTHS[b.getMonth()].slice(0,3)} ${b.getFullYear()}`);
  } else setTitle(`${DOW[(cur.getDay()+6)%7]}, ${cur.getDate()} ${MONTHS[cur.getMonth()]} ${cur.getFullYear()}`);

  const n = days.length, todayS = iso(new Date());
  const tpl = `56px repeat(${n}, 1fr)`;
  let h = `<div class="tg"><div class="tg-head" style="grid-template-columns:${tpl}"><div></div>` +
    days.map(d => `<div class="${iso(d)===todayS?"today":""}"><span class="dn" data-goto="${iso(d)}">${DOW[(d.getDay()+6)%7]} ${d.getDate()}</span></div>`).join("") + `</div>`;
  h += `<div class="allday-row" style="grid-template-columns:${tpl}"><div>cały dzień</div>` +
    days.map(d => `<div class="allday" data-date="${iso(d)}">${tasksOn(iso(d)).filter(t => !t.start).map(t => chipHTML(t, iso(d))).join("")}</div>`).join("") + `</div>`;
  h += `<div class="tg-body" id="tgb"><div class="tg-grid" style="grid-template-columns:${tpl}"><div class="hours">` +
    Array.from({length:24}, (_,i) => `<div>${i?pad(i)+":00":""}</div>`).join("") + `</div>`;
  for(const d of days){
    const ds = iso(d), timed = tasksOn(ds).filter(t => t.start);
    h += `<div class="col${ds===todayS?" today":""}" data-date="${ds}">` + layoutDay(timed).map(ev => {
      const t = ev.t, top = ev.s/60*HOUR, ht = Math.max(18,(ev.e-ev.s)/60*HOUR - 1);
      const w = 100/ev.n;
      return `<div class="ev p${t.priority} st-${t.status}" draggable="true" data-id="${t.id}" style="${colorStyle(t)}--pg:${t.progress}%;top:${top}px;height:${ht}px;left:calc(${ev.c*w}% + 1px);width:calc(${w}% - 3px)">` +
             `${stIcon(t)}${esc(t.title)}<small>${t.start}–${toHM(ev.e)}${namesOf(t).length ? " · " + esc(namesOf(t).join(", ")) : ""}</small><span class="rz" data-rz="${t.id}"></span></div>`;
    }).join("") + (ds===todayS ? `<div class="nowline" style="top:${(new Date().getHours()*60+new Date().getMinutes())/60*HOUR}px"></div>` : "") + `</div>`;
  }
  main.innerHTML = h + `</div></div></div>`;

  const body = document.getElementById("tgb");
  body.scrollTop = (window._tgScroll != null ? window._tgScroll : 7*HOUR);
  body.addEventListener("scroll", () => window._tgScroll = body.scrollTop);

  // upuszczanie na kolumnę godzinową
  main.querySelectorAll(".col").forEach(c => {
    c.addEventListener("dblclick", e => {
      if(e.target.closest(".ev")) return;
      const m = snap((e.clientY - c.getBoundingClientRect().top)/HOUR*60);
      openDialog(null, c.dataset.date, toHM(m));
    });
    c.addEventListener("dragover", e => { if(drag || ext(e)){ e.preventDefault(); c.classList.add("over"); } });
    c.addEventListener("dragleave", () => c.classList.remove("over"));
    c.addEventListener("drop", e => {
      e.preventDefault(); c.classList.remove("over");
      if(!drag){
        if(ext(e)) handleMailDrop(e.dataTransfer, c.dataset.date, toHM(snap((e.clientY - c.getBoundingClientRect().top)/HOUR*60)));
        return;
      }
      const t = byId(drag.id); if(!t) return;
      if(isMulti(t)){ shiftBy(t, daysBetween(drag.grab, c.dataset.date)); save(); render(); return; }   // wielodniowe zostaje całodniowe
      const top = e.clientY - c.getBoundingClientRect().top - drag.offY;
      const dur = t.start && t.end ? toMin(t.end) - toMin(t.start) : 60;
      const s = Math.max(0, Math.min(1440 - Math.max(dur,SNAP), snap(top/HOUR*60)));
      t.date = t.end_date = c.dataset.date; t.start = toHM(s); t.end = toHM(s + dur);
      save(); render();
    });
  });
  // upuszczanie na pasek "cały dzień"
  main.querySelectorAll(".allday").forEach(c => {
    c.addEventListener("dblclick", e => { if(!e.target.closest(".chip")) openDialog(null, c.dataset.date); });
    c.addEventListener("dragover", e => { if(drag || ext(e)){ e.preventDefault(); c.classList.add("over"); } });
    c.addEventListener("dragleave", () => c.classList.remove("over"));
    c.addEventListener("drop", e => {
      e.preventDefault(); c.classList.remove("over");
      if(!drag){ if(ext(e)) handleMailDrop(e.dataTransfer, c.dataset.date); return; }
      const t = byId(drag.id); if(!t) return;
      if(!isMulti(t)){ t.start = ""; t.end = ""; }
      shiftBy(t, daysBetween(drag.grab, c.dataset.date)); save(); render();
    });
  });
  bindChips(main);
  bindSpanHandles(main);
  main.querySelectorAll("[data-goto]").forEach(s => s.onclick = () => { cur = parse(s.dataset.goto); view = "day"; render(); });

  // zmiana długości (uchwyt na dole kafelka)
  main.querySelectorAll("[data-rz]").forEach(hd => {
    hd.addEventListener("mousedown", e => {
      e.preventDefault(); e.stopPropagation();
      const ev = hd.parentElement; ev.draggable = false;
      const t = byId(hd.dataset.rz), y0 = e.clientY, s = toMin(t.start);
      const e0 = t.end ? toMin(t.end) : s + 60;
      const move = m => {
        const end = Math.max(s + SNAP, Math.min(1440, snap(e0 + (m.clientY - y0)/HOUR*60)));
        ev.style.height = ((end - s)/60*HOUR - 1) + "px"; ev._end = end;
      };
      const up = () => {
        document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up);
        if(ev._end){ t.end = toHM(ev._end); save(); } render();
      };
      document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
    });
    hd.addEventListener("click", e => e.stopPropagation());
  });
}
const snap = m => Math.round(m/SNAP)*SNAP;
const byId = id => tasks.find(t => t.id === id);

/* ================= dialog ================= */
const dlg = document.getElementById("dlg");
let editing = null;
function openDialog(id, date, start, pre){          // pre = {title, notes} — wstępnie wypełnione np. z maila
  editing = id ? byId(id) : null;
  const preset = (!editing && filterPerson && filterPerson !== "__none") ? [filterPerson] : [];
  const d0 = date || iso(cur);
  const t = editing || {title: (pre && pre.title) || "", date: d0, end_date: d0, start: start || "", end: start ? toHM(toMin(start)+60) : "", priority:1, status:"pending", progress:0, notes: (pre && pre.notes) || "", assignees: preset, series: ""};
  document.getElementById("dlgTitle").textContent = editing ? "Edytuj zadanie" : "Nowe zadanie";
  fTitle.value = t.title; fDate.value = t.date; fDate2.value = isMulti(t) ? endOf(t) : ""; fPrio.value = t.priority;
  fStart.value = t.start; fEnd.value = t.end; fNotes.value = t.notes || "";
  draft = {status: t.status, progress: t.progress}; syncDraft();
  draftColor = t.color || ""; drawColors();
  pickSel = new Set(t.assignees || []); updatePeopleBtn();
  syncMulti();
  // powtarzanie: dla nowego (lub jeszcze niecyklicznego) zadania wybór reguły, dla wystąpienia serii informacja
  const inSeries = !!(editing && t.series);
  recBlock.hidden = inSeries; seriesInfo.hidden = !inSeries;
  fRec.value = "none"; fRecN.value = 10; fRecUntil.value = ""; recOpts.hidden = true; fApplyNext.checked = false;
  if(inSeries){
    const all = tasks.filter(x => x.series === t.series).sort((a, b) => a.date.localeCompare(b.date));
    seriesText.textContent = `🔁 Zadanie cykliczne — to ${all.indexOf(t) + 1}. z ${all.length}.`;
  }
  document.getElementById("del").style.visibility = editing ? "visible" : "hidden";
  fNext.style.visibility = "visible";
  dlg.showModal(); fTitle.focus();
}
// wybór koloru zadania w oknie edycji: ↺ = domyślny (wg priorytetu), paleta, własny kolor
let draftColor = "";
function drawColors(){
  const on = c => (c === draftColor ? " on" : "");
  fColors.innerHTML = `<button type="button" class="swatch def${on("")}" data-c="" title="Domyślny (wg priorytetu)">↺</button>` +
    PALETTE.map(c => `<button type="button" class="swatch${on(c)}" data-c="${c}" style="background:${c}" title="${c}"></button>`).join("") +
    `<input type="color" id="fColorCustom" value="${draftColor || "#3b6cf6"}" title="Własny kolor">`;
  fColors.querySelectorAll(".swatch").forEach(b => b.onclick = () => { draftColor = b.dataset.c; drawColors(); });
  fColors.querySelector("#fColorCustom").oninput = e => { draftColor = e.target.value.toLowerCase(); fColors.querySelectorAll(".swatch").forEach(s => s.classList.remove("on")); };
}
let draft = {status: "pending", progress: 0};
function syncDraft(){ fStatus.value = draft.status; fProg.value = draft.progress; fProgVal.textContent = draft.progress + "%"; }
fStatus.onchange = () => { applyStatus(draft, fStatus.value); syncDraft(); };
fProg.oninput = () => { applyProgress(draft, +fProg.value); syncDraft(); };

// zadanie wielodniowe jest całodniowe: godziny są wtedy nieaktywne
function syncMulti(){
  fDate2.min = fDate.value || "";
  const multi = !!(fDate2.value && fDate.value && fDate2.value > fDate.value);
  if(multi){ fStart.value = ""; fEnd.value = ""; }
  fStart.disabled = fEnd.disabled = multi;
  multiHint.hidden = !multi;
}
fDate.onchange = () => { if(fDate2.value && fDate2.value < fDate.value) fDate2.value = ""; syncMulti(); };
fDate2.onchange = syncMulti;
fRec.onchange = () => { recOpts.hidden = fRec.value === "none"; };

fNext.onclick = () => {      // przenieś na przyszły tydzień (zachowuje liczbę dni zadania)
  const ds = nextWeekDate(fDate.value || iso(cur));
  if(editing){ moveToDate(editing, ds); save(); dlg.close(); render(); note(""); return; }
  const delta = daysBetween(fDate.value || iso(cur), ds);
  fDate.value = ds;
  if(fDate2.value) fDate2.value = iso(addDays(parse(fDate2.value), delta));
  syncMulti();
};

/* ---- wybór osób: osobne, duże okno ---- */
let pickSel = new Set();
const pickdlg = document.getElementById("pickdlg");
function updatePeopleBtn(){
  const names = sortedPeople().filter(p => pickSel.has(p.id)).map(p => p.name);
  fPeopleBtn.textContent = names.length
    ? "👥 " + (names.length > 3 ? names.slice(0, 3).join(", ") + ` +${names.length - 3}` : names.join(", "))
    : "👥 Wybierz osoby…";
  fPeopleBtn.title = names.join("\n");
}
function drawPick(){
  const q = pkSearch.value.trim().toLowerCase();
  const list = sortedPeople().filter(p => !q || p.name.toLowerCase().includes(q));
  pkList.innerHTML = list.length ? list.map(p =>
    `<label><input type="checkbox" value="${esc(p.id)}"${pickSel.has(p.id) ? " checked" : ""}> ${esc(p.name)}</label>`).join("")
    : `<div class="empty">${people.length ? "Brak pasujących osób." : "Brak osób — dodaj poniżej."}</div>`;
  pkList.querySelectorAll("input").forEach(i => i.onchange = () => { i.checked ? pickSel.add(i.value) : pickSel.delete(i.value); updatePeopleBtn(); });
}
fPeopleBtn.onclick = () => { pkSearch.value = ""; pkNew.value = ""; drawPick(); pickdlg.showModal(); pkSearch.focus(); };
pkSearch.oninput = drawPick;
pkClear.onclick = () => { pickSel.clear(); drawPick(); updatePeopleBtn(); };
pkDone.onclick = () => pickdlg.close();
function addPerson(name){
  name = name.trim().slice(0, 100); if(!name) return null;
  const known = people.find(p => p.name.toLowerCase() === name.toLowerCase());
  if(known) return known;
  const p = {id: uid(), name}; people.push(p); return p;
}
pkAdd.onclick = () => {
  const p = addPerson(pkNew.value); if(!p) return;
  pickSel.add(p.id); pkNew.value = ""; pkSearch.value = ""; drawPick(); updatePeopleBtn(); save(); fillPersonFilter();
};
pkNew.addEventListener("keydown", e => { if(e.key === "Enter"){ e.preventDefault(); pkAdd.click(); } });

/* ---- powtarzanie: tworzymy kolejne zadania serii (każde można edytować osobno) ---- */
const addMonths = (s, n) => { const m = s.getMonth() + n, last = new Date(s.getFullYear(), m + 1, 0).getDate(); return new Date(s.getFullYear(), m, Math.min(s.getDate(), last)); };
function recurDates(start, kind, count, until){
  const s = parse(start), out = [start], max = Math.max(2, Math.min(+count || 10, 200));
  let d = new Date(s), i = 0;
  while(out.length < max && i < 4000){
    i++;
    if(kind === "daily") d = addDays(s, i);
    else if(kind === "workdays"){ do{ d = addDays(d, 1); }while(d.getDay() === 0 || d.getDay() === 6); }
    else if(kind === "weekly") d = addDays(s, 7 * i);
    else if(kind === "biweekly") d = addDays(s, 14 * i);
    else if(kind === "monthly") d = addMonths(s, i);
    else if(kind === "yearly") d = addMonths(s, 12 * i);
    else break;
    const ds = iso(d);
    if(until && ds > until) break;
    out.push(ds);
  }
  return out;
}
function makeSeries(first, kind, count, until){
  const sid = uid(); first.series = sid;
  const len = daysBetween(first.date, endOf(first)), copies = [];
  for(const ds of recurDates(first.date, kind, count, until).slice(1)){
    const c = Object.assign({}, first, {id: uid(), date: ds, end_date: iso(addDays(parse(ds), len)),
                                        status: "pending", progress: 0, assignees: [...first.assignees]});
    copies.push(c);
  }
  return copies;
}

form.addEventListener("submit", e => {
  if(e.submitter && e.submitter.value !== "save") return;
  const t = editing || {id: uid(), series: ""};
  const d1 = fDate.value, d2 = fDate2.value && fDate2.value > d1 ? fDate2.value : d1, multi = d2 > d1;
  t.title = fTitle.value.trim(); t.date = d1; t.end_date = d2; t.priority = +fPrio.value;
  t.start = multi ? "" : fStart.value; t.end = (multi || !fStart.value) ? "" : (fEnd.value || toHM(toMin(fStart.value)+60));
  if(t.end && toMin(t.end) <= toMin(t.start)) t.end = toHM(toMin(t.start)+SNAP);
  t.notes = fNotes.value; t.status = draft.status; t.progress = draft.progress; t.assignees = [...pickSel]; t.color = draftColor;
  let extra = [];
  if(!t.series && fRec.value !== "none") extra = makeSeries(t, fRec.value, fRecN.value, fRecUntil.value);
  else if(editing && t.series && fApplyNext.checked){        // zmiany do kolejnych zadań serii (bez dat i statusu)
    tasks.filter(x => x.series === t.series && x !== t && x.date > t.date).forEach(x => {
      x.title = t.title; x.priority = t.priority; x.notes = t.notes; x.assignees = [...t.assignees]; x.color = t.color;
      if(!isMulti(x)){ x.start = t.start; x.end = t.end; }
    });
  }
  if(!editing) tasks.push(t);
  tasks.push(...extra);
  save(); render();
  if(extra.length) note(`Utworzono serię: ${extra.length + 1} zadań.`, true);
});

/* ---- usuwanie: dla serii pytamy, czy usunąć tylko to zadanie, czy także kolejne ---- */
function askDeleteSeries(later){
  delText.textContent = `To zadanie należy do serii cyklicznej. Kolejnych zadań w serii: ${later}.`;
  return new Promise(res => {
    let choice = null;
    const done = c => { choice = c; deldlg.close(); };
    delOne.onclick = () => done("one"); delFol.onclick = () => done("following"); delNo.onclick = () => done(null);
    deldlg.addEventListener("close", () => res(choice), {once: true});
    deldlg.showModal();
  });
}

/* ================= osoby ================= */
const pdlg = document.getElementById("pdlg");
function drawPeople(){
  pList.innerHTML = people.length ? sortedPeople().map(p => {
    const n = tasks.filter(t => (t.assignees||[]).includes(p.id)).length;
    return `<div class="prow" data-id="${esc(p.id)}"><input type="text" value="${esc(p.name)}" maxlength="100" aria-label="Nazwa osoby"><small>${n} zad.</small><button class="btn danger" type="button" data-del="${esc(p.id)}">Usuń</button></div>`;
  }).join("") : `<div class="empty">Brak osób.</div>`;
  pList.querySelectorAll(".prow input").forEach(inp => inp.addEventListener("change", () => {
    const p = people.find(x => x.id === inp.parentElement.dataset.id), v = inp.value.trim();
    if(p && v){ p.name = v; save(); render(); } else if(p) inp.value = p.name;
  }));
  pList.querySelectorAll("[data-del]").forEach(b => b.onclick = () => {
    const p = people.find(x => x.id === b.dataset.del); if(!p) return;
    if(!confirm(`Usunąć osobę „${p.name}”? Zostanie zdjęta ze wszystkich zadań.`)) return;
    people = people.filter(x => x !== p);
    tasks.forEach(t => { t.assignees = (t.assignees || []).filter(a => a !== p.id); });
    save(); drawPeople(); render();
  });
}
ppl.onclick = () => { pNew.value = ""; drawPeople(); pdlg.showModal(); pNew.focus(); };
pAdd.onclick = () => { if(addPerson(pNew.value)){ pNew.value = ""; save(); drawPeople(); render(); } };
pNew.addEventListener("keydown", e => { if(e.key === "Enter"){ e.preventDefault(); pAdd.click(); } });
pClose.onclick = () => pdlg.close();
fPerson.onchange = () => { filterPerson = fPerson.value; render(); };

/* ================= lista zadań pod kalendarzem ================= */
function periodRange(){
  if(view === "month") return [iso(new Date(cur.getFullYear(), cur.getMonth(), 1)), iso(new Date(cur.getFullYear(), cur.getMonth()+1, 0))];
  if(view === "week"){ const m = mondayOf(cur); return [iso(m), iso(addDays(m, 6))]; }
  return [iso(cur), iso(cur)];
}
const WD = ["nd","pon","wt","śr","czw","pt","sob"];
const fmtDate = ds => { const d = parse(ds); return `${WD[d.getDay()]}, ${pad(d.getDate())}.${pad(d.getMonth()+1)}.${d.getFullYear()}`; };
// krótki termin na liście: tylko dzień i data (bez godziny i dopisku „cały dzień”); dla zadań wielodniowych zakres
const fmtShort = t => {
  if(!isMulti(t)) return fmtDate(t.date);
  const a = parse(t.date), b = parse(endOf(t)), s = d => `${WD[d.getDay()]} ${pad(d.getDate())}.${pad(d.getMonth()+1)}`;
  return a.getFullYear() === b.getFullYear() ? `${s(a)} – ${s(b)}.${b.getFullYear()}` : `${fmtDate(t.date)} – ${fmtDate(endOf(t))}`;
};
// kolejność wykonania: data, potem godzina (zadania całodniowe najpierw), potem priorytet, potem tytuł
const byDue = (a,b) => a.date.localeCompare(b.date) || (a.start||"").localeCompare(b.start||"") || b.priority - a.priority || a.title.localeCompare(b.title);
function renderList(){
  const todayS = iso(new Date()), [from, to] = periodRange();
  let rows = visibleTasks();
  if(hideDone) rows = rows.filter(t => t.status !== "done");
  if(listScope === "today") rows = rows.filter(t => endOf(t) >= todayS);
  else if(listScope === "period") rows = rows.filter(t => t.date <= to && endOf(t) >= from);
  rows.sort(byDue);
  const el = document.getElementById("list");
  let h = `<div class="list-head"><h2>Lista zadań (${rows.length})</h2>
    <label>Zakres <select id="lScope"><option value="all">Wszystkie</option><option value="today">Od dziś</option><option value="period">Widoczny okres</option></select></label>
    <label><input type="checkbox" id="lHide"> Ukryj zrobione</label></div>`;
  if(!rows.length) h += `<div class="empty">Brak zadań do wyświetlenia.</div>`;
  else {
    h += `<div class="list-scroll"><table class="tasks"><colgroup><col class="c-st"><col class="c-when"><col class="c-title"><col class="c-who"><col class="c-prio"><col class="c-prog"></colgroup><thead><tr><th title="Status — prawy przycisk myszy zmienia status"></th><th>Termin</th><th>Zadanie</th><th>Osoby</th><th>Priorytet</th><th>Postęp</th></tr></thead><tbody>`;
    let prev = "";
    for(const t of rows){
      const done = t.status === "done";
      const cls = ["trow", t.date !== prev && prev ? "newday" : "", occursOn(t, todayS) ? "istoday" : "", endOf(t) < todayS && !done ? "late" : "", "st-" + t.status].join(" ");
      prev = t.date;
      const when = fmtDate(t.date) + (t.series ? " 🔁" : "");      // lista: tylko początek (zakres wielodniowy widać w kalendarzu)
      h += `<tr class="${cls}" data-id="${esc(t.id)}"${t.color ? ` style="--tc:${t.color}"` : ""}><td class="stcell" title="${STATUS[t.status].label}">${STATUS[t.status].icon}</td>` +
           `<td class="when">${when}</td><td class="tcell"><input class="tinp" type="text" maxlength="300" value="${esc(t.title)}" data-title="${esc(t.id)}" aria-label="Tytuł zadania — edytuj bezpośrednio"></td><td>${esc(namesOf(t).join(", "))}</td><td><span class="badge p${t.priority}">${["", "Niski", "Średni", "Wysoki"][t.priority]}</span></td>` +
           `<td><span class="pbar"><i style="width:${t.progress}%"></i></span> <small>${t.progress}%</small></td></tr>`;
    }
    h += `</tbody></table></div>`;
  }
  el.innerHTML = h;
  lScope.value = listScope; lHide.checked = hideDone;
  lScope.onchange = () => { listScope = lScope.value; renderList(); };
  lHide.onchange = () => { hideDone = lHide.checked; renderList(); };
  el.querySelectorAll("tr.trow").forEach(r => r.addEventListener("click", e => { if(!e.target.closest(".tinp")) openDialog(r.dataset.id); }));
  el.querySelectorAll(".tinp").forEach(inp => {          // edycja tytułu bezpośrednio w komórce
    const t = byId(inp.dataset.title);
    inp.addEventListener("keydown", e => {
      if(e.key === "Enter") inp.blur();
      else if(e.key === "Escape"){ inp.value = t.title; inp.blur(); }
      e.stopPropagation();
    });
    inp.addEventListener("change", () => {
      const v = inp.value.trim();
      if(!v){ inp.value = t.title; return; }
      if(v !== t.title){ t.title = v; inp.value = v; save(); renderCal(); }
    });
  });
}

/* ================= przenoszenie na przyszły tydzień / na dziś ================= */
const startOfToday = () => { const d = new Date(); d.setHours(0,0,0,0); return d; };
// +7 dni, a gdy wypada to jeszcze w tym tygodniu (zadanie zaległe) – ten sam dzień tygodnia w przyszłym tygodniu
function nextWeekDate(ds){
  const orig = parse(ds), moved = addDays(orig, 7), nextMon = addDays(mondayOf(startOfToday()), 7);
  return iso(moved < nextMon ? addDays(nextMon, (orig.getDay() + 6) % 7) : moved);
}
const unfinished = () => visibleTasks().filter(t => t.status !== "done");
function bulkMove(kind){
  closeMenu2();
  const todayS = iso(new Date()), weekEnd = iso(addDays(mondayOf(startOfToday()), 6));
  const overdue = unfinished().filter(t => endOf(t) < todayS);
  const rows = kind === "next" ? unfinished().filter(t => endOf(t) <= weekEnd) : overdue;
  const scope = filterPerson ? " (zgodnie z wybranym filtrem osoby)" : "";
  if(!rows.length){ alert(kind === "next" ? "Brak niezakończonych zadań z tego tygodnia lub zaległych do przeniesienia." : "Brak zaległych niezakończonych zadań do przeniesienia."); return; }
  const msg = kind === "today"
    ? `Przenieść ${rows.length} zaległych niezakończonych zadań na dziś${scope}?`
    : kind === "overdueNext" ? `Przenieść ${rows.length} zaległych niezakończonych zadań na przyszły tydzień${scope}?`
    : `Przenieść ${rows.length} niezakończonych zadań (zaległych i z tego tygodnia) na przyszły tydzień${scope}?`;
  if(!confirm(msg)) return;
  rows.forEach(t => moveToDate(t, kind === "today" ? todayS : nextWeekDate(t.date)));
  save(); render();
}
function closeMenu2(){ moveMenu.open = false; }
document.addEventListener("click", e => { if(!e.target.closest("#moveMenu")) closeMenu2(); });
mvToday.onclick = () => bulkMove("today");
mvNext.onclick = () => bulkMove("next");

/* ================= menu prawego przycisku: status, postęp, przeniesienie ================= */
let ctxId = null;
const ctx = document.getElementById("ctx");
function hideCtx(){ ctx.hidden = true; ctxId = null; }
function showCtx(id, x, y){
  const t = byId(id); if(!t) return;
  ctxId = id;
  ctx.innerHTML =
    `<div class="ctx-icons">` + Object.keys(STATUS).map(s =>
      `<button type="button" data-s="${s}" class="${t.status === s ? "on" : ""}" title="${STATUS[s].label}"><span>${STATUS[s].icon}</span><small>${STATUS[s].label}</small></button>`).join("") + `</div>` +
    `<div class="ctx-prog"><label>Postęp: <b id="ctxPv">${t.progress}%</b></label><input type="range" id="ctxP" min="0" max="100" step="25" value="${t.progress}" list="progTicks"></div>` +
    `<div class="ctx-colors" title="Kolor zadania"><button type="button" class="swatch def${t.color ? "" : " on"}" data-cc="" title="Domyślny (wg priorytetu)">↺</button>` +
      PALETTE.map(c => `<button type="button" class="swatch${t.color === c ? " on" : ""}" data-cc="${c}" style="background:${c}" title="${c}"></button>`).join("") + `</div>` +
    `<hr><button type="button" class="ctx-item" data-act="next">➡ Przenieś na przyszły tydzień</button>` +
    `<button type="button" class="ctx-item" data-act="edit">✏ Edytuj…</button>` +
    `<button type="button" class="ctx-item ctx-del" data-act="del">🗑 Usuń zadanie</button>`;
  ctx.hidden = false;
  const r = ctx.getBoundingClientRect();
  ctx.style.left = Math.max(4, Math.min(x, innerWidth - r.width - 6)) + "px";
  ctx.style.top = Math.max(4, Math.min(y, innerHeight - r.height - 6)) + "px";
  ctx.querySelectorAll("[data-s]").forEach(b => b.onclick = () => { applyStatus(t, b.dataset.s); save(); hideCtx(); render(); });
  ctx.querySelectorAll("[data-cc]").forEach(b => b.onclick = () => { t.color = b.dataset.cc; save(); hideCtx(); render(); });
  const p = ctx.querySelector("#ctxP");
  p.oninput = () => { ctx.querySelector("#ctxPv").textContent = p.value + "%"; };
  p.onchange = () => { applyProgress(t, +p.value); save(); hideCtx(); render(); };
  ctx.querySelector('[data-act="next"]').onclick = () => { moveToDate(t, nextWeekDate(t.date)); save(); hideCtx(); render(); };
  ctx.querySelector('[data-act="edit"]').onclick = () => { hideCtx(); openDialog(t.id); };
  ctx.querySelector('[data-act="del"]').onclick = async () => { hideCtx(); await deleteTask(t); render(); };
}
document.addEventListener("contextmenu", e => {
  const el = e.target.closest("[data-id]");
  if(!el || e.target.closest("dialog")){ if(!e.target.closest("#ctx")) hideCtx(); return; }
  e.preventDefault(); showCtx(el.dataset.id, e.clientX, e.clientY);
});
document.addEventListener("mousedown", e => { if(!ctx.hidden && !e.target.closest("#ctx")) hideCtx(); });
document.addEventListener("keydown", e => { if(e.key === "Escape") hideCtx(); });
window.addEventListener("blur", hideCtx);
document.addEventListener("scroll", hideCtx, true);

/* ================= dymek z opisem zadania po najechaniu ================= */
const tipEl = document.getElementById("tip");
let tipTimer = null, tipFor = null, mouseX = 0, mouseY = 0;
function hideTip(){ clearTimeout(tipTimer); tipTimer = null; tipFor = null; if(tipEl) tipEl.hidden = true; }
function tipHTML(t){
  const when = isMulti(t) ? `${fmtDate(t.date)} – ${fmtDate(endOf(t))}` : fmtDate(t.date) + (t.start ? ` · ${t.start}${t.end ? "–" + t.end : ""}` : "");
  const names = namesOf(t), notes = (t.notes || "").trim();
  const meta = [`📅 ${esc(when)}`, `${STATUS[t.status].icon} ${STATUS[t.status].label}${t.progress ? ` · ${t.progress}%` : ""}`,
                names.length ? `👥 ${esc(names.join(", "))}` : "", t.series ? "🔁 Zadanie cykliczne" : ""].filter(Boolean);
  return `<div class="tip-title">${esc(t.title)}</div><div class="tip-meta">${meta.join("<br>")}</div>` +
         (notes ? `<div class="tip-notes">${esc(notes.length > 700 ? notes.slice(0, 700) + "…" : notes)}</div>` : `<div class="tip-none">Brak opisu</div>`);
}
function showTip(t){
  if(!tipEl || !byId(t.id)) return;
  tipEl.style.setProperty("--tc", t.color || `var(--p${t.priority})`);
  tipEl.innerHTML = tipHTML(t); tipEl.hidden = false;
  const r = tipEl.getBoundingClientRect();
  let x = mouseX + 16, y = mouseY + 18;
  if(x + r.width > innerWidth - 8) x = Math.max(8, mouseX - r.width - 12);          // brak miejsca z prawej: po lewej od kursora
  if(y + r.height > innerHeight - 8) y = Math.max(8, mouseY - r.height - 12);       // brak miejsca na dole: nad kursorem
  tipEl.style.left = x + "px"; tipEl.style.top = y + "px";
}
document.addEventListener("mousemove", e => { mouseX = e.clientX; mouseY = e.clientY; });
document.addEventListener("mouseover", e => {
  if(drag || !ctx.hidden || e.target.closest("dialog") || e.target.closest("#tip")) return;
  const el = e.target.closest("[data-id]");
  if(!el || el === tipFor) return;
  const t = byId(el.dataset.id); if(!t) return;
  hideTip(); tipFor = el;
  tipTimer = setTimeout(() => { if(tipFor === el && el.isConnected) showTip(t); }, 350);
});
document.addEventListener("mouseout", e => {
  const el = e.target.closest("[data-id]");
  if(el && el === tipFor && !el.contains(e.relatedTarget)) hideTip();
});
for(const ev of ["mousedown", "dragstart", "contextmenu", "keydown", "wheel", "blur"]) window.addEventListener(ev, hideTip, true);
// usuwanie zadania (dla serii pyta, czy usunąć tylko to, czy także kolejne); zwraca true, gdy usunięto
async function deleteTask(t){
  const later = t.series ? tasks.filter(x => x.series === t.series && x !== t && x.date > t.date).length : 0;
  if(later){
    const choice = await askDeleteSeries(later);
    if(!choice) return false;
    tasks = tasks.filter(x => x !== t && !(choice === "following" && x.series === t.series && x.date > t.date));
  } else {
    if(!confirm(`Usunąć zadanie „${t.title}”?`)) return false;
    tasks = tasks.filter(x => x !== t);
  }
  save();
  return true;
}
document.getElementById("del").onclick = async () => {
  if(editing && await deleteTask(editing)){ dlg.close(); render(); }
};

/* ================= nawigacja ================= */
function shift(dir){
  if(view === "month") cur = new Date(cur.getFullYear(), cur.getMonth() + dir, 1);
  else cur = addDays(cur, dir * (view === "week" ? 7 : 1));
  render();
}
prev.onclick = () => shift(-1); next.onclick = () => shift(1);
today.onclick = () => { cur = new Date(); cur.setHours(0,0,0,0); render(); };
add.onclick = () => openDialog(null, iso(cur));
document.querySelectorAll("#views .btn").forEach(b => b.onclick = () => { view = b.dataset.v; render(); });
document.querySelectorAll("#layoutSeg .btn").forEach(b => b.onclick = () => { layout = b.dataset.l; render(); });
document.querySelectorAll("#themeSeg .btn").forEach(b => b.onclick = () => { theme = b.dataset.t; applyTheme(); saveTheme(); });
document.addEventListener("keydown", e => {
  if(dlg.open || pdlg.open || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
  if(e.key === "ArrowLeft") shift(-1); else if(e.key === "ArrowRight") shift(1);
  else if(e.key === "m") { view="month"; render(); } else if(e.key === "w") { view="week"; render(); } else if(e.key === "d") { view="day"; render(); }
});


/* ================= eksport / import ================= */
const closeMenu = () => { dataMenu.open = false; };
document.addEventListener("click", e => { if(!e.target.closest("#dataMenu")) closeMenu(); });
async function doExport(){            // kopia zapasowa JSON
  closeMenu();
  try{
    if(DESKTOP){
      const name = await api().export_json(currentData());
      if(name) note("Wyeksportowano: " + name, true);
      return;
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(currentData(), null, 2)], {type:"application/json"}));
    a.download = `tasklist-${iso(new Date())}.json`; a.click(); URL.revokeObjectURL(a.href);
  }catch(e){ note("Eksport nie powiódł się: " + errText(e)); }
}
function applyImport(raw){
  const d = normalize(raw);
  if(confirm(`Zaimportować ${d.tasks.length} zadań i ${d.people.length} osób? Obecne dane zostaną zastąpione.`)){
    tasks = d.tasks; people = d.people; filterPerson = ""; save(); render(); note("");
  }
}
async function doImport(){
  closeMenu();
  if(!DESKTOP){ file.click(); return; }
  try{ const data = await api().import_json(); if(data) applyImport(data); }
  catch(e){ note("Import nie powiódł się: " + errText(e)); }
}
exp.onclick = doExport; imp.onclick = doImport;

/* ================= zadanie z maila: przeciągnij wiadomość z Outlooka (lub .msg/.eml) na kalendarz ================= */
function ext(e){                    // czy przeciągany jest obiekt z zewnątrz (plik / tekst), a nie zadanie z kalendarza
  if(drag || !e.dataTransfer) return false;
  const t = [...(e.dataTransfer.types || [])];
  return t.includes("Files") || t.includes("text/plain") || t.includes("text/uri-list") || t.includes("text/html");
}
const toB64 = f => new Promise((ok, fail) => {
  const fr = new FileReader();
  fr.onload = () => ok(String(fr.result).split(",")[1] || "");
  fr.onerror = () => fail(new Error("Nie udało się odczytać przeciągniętego pliku."));
  fr.readAsDataURL(f);
});
function mailToDialog(mail, date, start){
  openDialog(null, date || iso(new Date()), start, {title: mail.subject, notes: mail.notes});
  note("Zadanie z wiadomości — ustaw termin, osoby i zapisz.", true);
}
async function handleMailDrop(dt, date, start){
  if(dlg.open || pdlg.open) return;
  try{
    const f = [...(dt.files || [])].find(x => /\.(msg|eml)$/i.test(x.name));
    if(f){
      if(!DESKTOP) throw new Error("Wczytywanie plików .msg i .eml działa w aplikacji okienkowej (TaskListAK.exe).");
      if(f.size > 25 * 1024 * 1024) throw new Error("Wiadomość jest zbyt duża (limit 25 MB).");
      note("Wczytywanie wiadomości…", true);
      mailToDialog(await api().parse_mail(f.name, await toB64(f)), date, start);
      return;
    }
    if(dt.files && dt.files.length) throw new Error("Przeciągnij wiadomość z Outlooka lub plik .msg / .eml.");
    // brak pliku (np. Outlook w przeglądarce): użyj przeciągniętego tekstu — pierwsza linia jako tytuł
    const text = (dt.getData("text/plain") || dt.getData("Text") || dt.getData("text/uri-list") || "").trim();
    if(!text) throw new Error("Z przeciągniętego elementu nie udało się odczytać wiadomości. Zapisz mail jako .msg lub .eml i przeciągnij plik albo użyj Dane → Utwórz zadanie z maila.");
    const lines = text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    mailToDialog({subject: lines[0].slice(0, 300), notes: lines.length > 1 ? text.slice(0, 4000) : (/^https?:/i.test(text) ? "Link: " + text : "")}, date, start);
  }catch(e){ note("Nie utworzono zadania z maila: " + errText(e)); }
}
async function openMailFile(){
  closeMenu();
  try{ const mail = await api().open_mail(); if(mail) mailToDialog(mail); }
  catch(e){ note("Nie utworzono zadania z maila: " + errText(e)); }
}
mailOpen.onclick = openMailFile;
// upuszczenie poza dniem kalendarza: zadanie na dziś; blokada otwierania upuszczonego pliku przez okno
document.addEventListener("dragover", e => { if(ext(e)){ e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
document.addEventListener("drop", e => {
  if(e.defaultPrevented || !ext(e)) return;
  e.preventDefault(); handleMailDrop(e.dataTransfer, iso(new Date()));
});

/* ---- plik Excela: otwarcie (zapamiętywane i wczytywane przy starcie), zapis, zapis jako ---- */
async function openXlsx(){
  closeMenu();
  try{
    const r = await api().open_xlsx(); if(!r) return;
    const d = normalize(r.data);
    const warn = fileInfo && fileInfo.dirty ? `\n\nUwaga: plik ${fileInfo.name} ma niezapisane zmiany, które zostaną utracone.` : "";
    if(!confirm(`Otworzyć „${r.name}” (${d.tasks.length} zadań, ${d.people.length} osób)? Obecne dane zostaną zastąpione. Program zapamięta ten plik i wczyta go przy następnym uruchomieniu.${warn}`)) return;
    await flush();                                  // nie pozwól, by starszy zapis nadpisał nowy plik
    fileInfo = await api().accept_xlsx(r.token);
    tasks = d.tasks; people = d.people; filterPerson = "";
    render(); showFile(); note("Otwarto: " + r.name, true);
  }catch(e){ note("Nie otwarto pliku: " + errText(e)); }
}
async function saveXlsx(asNew){
  closeMenu();
  try{
    await flush();
    const f = await api().save_xlsx(currentData(), !!asNew);
    if(f){ fileInfo = f; showFile(); note("Zapisano w pliku: " + f.name, true); }
  }catch(e){ note("Zapis do Excela nie powiódł się: " + errText(e)); }
}
xlsImp.onclick = openXlsx; xlsSave.onclick = () => saveXlsx(false); xlsExp.onclick = () => saveXlsx(true);
saveBtn.onclick = async () => { saveBtn.disabled = true; try{ await saveXlsx(false); } finally{ saveBtn.disabled = false; } };
document.addEventListener("keydown", e => {
  if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s"){ e.preventDefault(); if(DESKTOP && started) saveXlsx(false); }
});
file.onchange = async () => {
  try{ applyImport(JSON.parse(await file.files[0].text())); }
  catch(e){ alert("Nieprawidłowy plik JSON."); }
  file.value = "";
};

/* ================= aktualizacje (tylko w aplikacji) ================= */
let installing = false, updateChecked = false;
function setUpdate(msg, canInstall){ updStatus.textContent = msg; install.hidden = !canInstall; }
chk.onclick = async () => {
  chk.disabled = true; setUpdate("Sprawdzanie aktualizacji…", false);
  try{
    const r = await api().check_updates();
    if(r.status === "available"){ setUpdate(`Dostępna wersja ${r.latest} (masz ${r.current}).`, true); }
    else if(r.status === "pending"){ setUpdate(`Wersja ${r.latest} jest w trakcie publikacji. Spróbuj za kilka minut.`, false); }
    else if(r.status === "current"){ setUpdate("Masz najnowszą wersję.", false); }
    else if(r.status === "unavailable"){ setUpdate("Brak opublikowanych wydań.", false); }
    else setUpdate(r.message || "Nie udało się sprawdzić aktualizacji.", false);
  }catch(e){ setUpdate("Nie udało się sprawdzić aktualizacji. " + errText(e), false); }
  finally{ chk.disabled = false; }
};
install.onclick = async () => {
  if(installing) return;
  if(!confirm("Pobrać aktualizację i ponownie uruchomić program? Twoje zadania są zapisane osobno i nie zostaną zmienione.")) return;
  installing = true; install.disabled = chk.disabled = true;
  try{
    await flush();
    setUpdate("Pobieranie i sprawdzanie aktualizacji…", false);
    await api().prepare_update();
    setUpdate("Aktualizacja gotowa. Program uruchomi się ponownie.", false);
    await api().install_update();
  }catch(e){ setUpdate("Nie zainstalowano aktualizacji: " + errText(e), false); }
  finally{ installing = false; install.disabled = chk.disabled = false; }
};
function initUpdates(){
  if(!DESKTOP) return;
  document.getElementById("updatebox").hidden = false;
  for(const id of ["xlsExp", "xlsImp", "xlsSave", "mailOpen", "saveBtn"]) document.getElementById(id).hidden = false;
  api().get_version().then(v => { ver.textContent = "v" + v; }).catch(() => {});
  if(!updateChecked){ updateChecked = true; setTimeout(() => chk.click(), 2500); }
}

/* ================= start ================= */
function seed(){
  const t = iso(new Date()), a = {id:uid(), name:"Nowak Anna"}, b = {id:uid(), name:"Kowalski Jan"};
      theme = (r.prefs && r.prefs.theme) || ""; applyTheme();
  return {people: [a, b], tasks: [
    {id:uid(), title:"Przykład: spotkanie zespołu", date:t, start:"10:00", end:"11:00", priority:2, status:"progress", progress:50, notes:"", assignees:[a.id, b.id]},
    {id:uid(), title:"Przykład: zadanie na cały dzień", date:t, start:"", end:"", priority:1, status:"pending", progress:0, notes:"", assignees:[]},
    {id:uid(), title:"Przykład: termin oddania raportu", date:iso(addDays(new Date(),2)), start:"15:30", end:"16:30", priority:3, status:"pending", progress:0, notes:"", assignees:[a.id]}
  ]};
}
async function boot(){
  if(started) return; started = true;
  try{
    if(DESKTOP){
      const r = await api().load_state();
      view = (r.prefs && r.prefs.view) || "month";
      layout = (r.prefs && r.prefs.layout) === "grid" ? "grid" : "board"; savedLayout = layout;
      readOnly = !!r.readonly;                       // nie nadpisuj pliku, którego nie da się odczytać
      const d = r.tasks ? normalize({people: r.people, tasks: r.tasks}) : (readOnly ? {people: [], tasks: []} : seed());
      tasks = d.tasks; people = d.people;
      if(r.tasks === null && !readOnly) save();
      note(r.warning || "");
      fileInfo = r.file || null; showFile();
    } else {
      let d = null;
      try{ d = normalize(JSON.parse(localStorage.getItem(KEY))); }catch(e){}
      try{ view = localStorage.getItem(KEY + "_view") || "month"; }catch(e){}
      try{ layout = localStorage.getItem(KEY + "_layout") === "grid" ? "grid" : "board"; savedLayout = layout; }catch(e){}
      try{ theme = localStorage.getItem(KEY + "_theme") || ""; }catch(e){} applyTheme();
      if(!d || !d.tasks.length) d = seed();
      tasks = d.tasks; people = d.people; save();
    }
  }catch(e){ readOnly = true; note("Nie udało się wczytać zadań: " + errText(e)); }
  render(); initUpdates();
}
if(DESKTOP){ if(api()) boot(); else window.addEventListener("pywebviewready", boot); } else boot();
setInterval(() => { if(started && view !== "month" && !dlg.open && !drag) render(); }, 5*60*1000);
