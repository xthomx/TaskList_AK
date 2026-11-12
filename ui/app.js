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
let view = "month";
let cur = new Date(); cur.setHours(0,0,0,0);
let drag = null;                 // {id, offY}
let started = false, readOnly = false, saveTimer = null, chain = Promise.resolve();
const api = () => window.pywebview && window.pywebview.api;
const errText = e => (e && (e.message || e.toString())) || "nieznany błąd";
function note(msg){ const el = document.getElementById("note"); el.textContent = msg || ""; el.hidden = !msg; }

/* ---- zapis: w aplikacji do pliku w %LOCALAPPDATA%\TaskListAK, w przeglądarce do localStorage ---- */
const currentData = () => ({people, tasks});
function normalize(d){        // akceptuje stary format (sama lista zadań z wersji 1.0)
  if(Array.isArray(d)) d = {people: [], tasks: d};
  if(!d || !Array.isArray(d.tasks)) throw new Error("Nieprawidłowy format danych.");
  const ppl = Array.isArray(d.people) ? d.people : [];
  return {people: ppl, tasks: d.tasks.map(t => Object.assign({assignees: []}, t))};
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
  chain = chain.then(() => api().save_data(snap)).then(() => note("")).catch(e => note("Zapis nie powiódł się: " + errText(e)));
  return chain;
}
let savedView = null;
function saveView(){
  if(view === savedView) return; savedView = view;
  if(DESKTOP){ if(api()) api().set_view(view).catch(() => {}); }
  else { try{ localStorage.setItem(KEY + "_view", view); }catch(e){} }
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
const tasksOn = ds => visibleTasks().filter(t => t.date === ds).sort(byTime);

/* ================= render ================= */
function render(){
  document.querySelectorAll("#views .btn").forEach(b => b.classList.toggle("active", b.dataset.v === view));
  fillPersonFilter();
  const cal = document.getElementById("cal");
  if(view === "month") renderMonth(cal); else renderTimeGrid(cal, view === "week");
  renderList();
  saveView();
}

function setTitle(s){ document.getElementById("title").textContent = s; }

function chipHTML(t){
  const time = t.start ? t.start + " " : "";
  const names = namesOf(t), who = names.length ? ` <span class="who">· ${esc(names.map(shortName).join(", "))}</span>` : "";
  const tip = esc(t.title) + (names.length ? " — " + esc(names.join(", ")) : "");
  return `<span class="chip p${t.priority}${t.done?" done":""}" draggable="true" data-id="${t.id}" title="${tip}">${time}${esc(t.title)}${who}</span>`;
}

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
  let h = `<div class="month">` + DOW.map(d => `<div class="dow">${d}</div>`).join("");
  for(let i=0;i<42;i++){
    const d = addDays(start,i), ds = iso(d);
    const cls = ["cell", d.getMonth()!==cur.getMonth()?"other":"", d.getDay()%6===0?"weekend":"", ds===todayS?"today":""].join(" ");
    h += `<div class="${cls}" data-date="${ds}"><span class="daynum" data-goto="${ds}">${d.getDate()}</span>${tasksOn(ds).map(chipHTML).join("")}</div>`;
  }
  main.innerHTML = h + "</div>";

  main.querySelectorAll(".cell").forEach(c => {
    c.addEventListener("dblclick", e => { if(!e.target.closest(".chip")) openDialog(null, c.dataset.date); });
    c.addEventListener("dragover", e => { if(drag){ e.preventDefault(); c.classList.add("over"); } });
    c.addEventListener("dragleave", () => c.classList.remove("over"));
    c.addEventListener("drop", e => {
      e.preventDefault(); c.classList.remove("over");
      if(drag){ const t = byId(drag.id); if(t){ t.date = c.dataset.date; save(); render(); } }
    });
  });
  bindChips(main);
  main.querySelectorAll("[data-goto]").forEach(s => s.onclick = () => { cur = parse(s.dataset.goto); view = "day"; render(); });
}

function bindChips(root){
  root.querySelectorAll("[data-id]").forEach(el => {
    el.addEventListener("dragstart", e => {
      const r = el.getBoundingClientRect();
      drag = { id: el.dataset.id, offY: e.clientY - r.top };
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", el.dataset.id);
      setTimeout(() => el.classList.add("dragging"), 0);
    });
    el.addEventListener("dragend", () => { drag = null; el.classList.remove("dragging"); });
    el.addEventListener("click", e => { e.stopPropagation(); openDialog(el.dataset.id); });
  });
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
    days.map(d => `<div class="allday" data-date="${iso(d)}">${tasksOn(iso(d)).filter(t => !t.start).map(chipHTML).join("")}</div>`).join("") + `</div>`;
  h += `<div class="tg-body" id="tgb"><div class="tg-grid" style="grid-template-columns:${tpl}"><div class="hours">` +
    Array.from({length:24}, (_,i) => `<div>${i?pad(i)+":00":""}</div>`).join("") + `</div>`;
  for(const d of days){
    const ds = iso(d), timed = tasksOn(ds).filter(t => t.start);
    h += `<div class="col${ds===todayS?" today":""}" data-date="${ds}">` + layoutDay(timed).map(ev => {
      const t = ev.t, top = ev.s/60*HOUR, ht = Math.max(18,(ev.e-ev.s)/60*HOUR - 1);
      const w = 100/ev.n;
      return `<div class="ev p${t.priority}${t.done?" done":""}" draggable="true" data-id="${t.id}" style="top:${top}px;height:${ht}px;left:calc(${ev.c*w}% + 1px);width:calc(${w}% - 3px)">` +
             `${esc(t.title)}<small>${t.start}–${toHM(ev.e)}${namesOf(t).length ? " · " + esc(namesOf(t).join(", ")) : ""}</small><span class="rz" data-rz="${t.id}"></span></div>`;
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
    c.addEventListener("dragover", e => { if(drag){ e.preventDefault(); c.classList.add("over"); } });
    c.addEventListener("dragleave", () => c.classList.remove("over"));
    c.addEventListener("drop", e => {
      e.preventDefault(); c.classList.remove("over");
      const t = drag && byId(drag.id); if(!t) return;
      const top = e.clientY - c.getBoundingClientRect().top - drag.offY;
      const dur = t.start && t.end ? toMin(t.end) - toMin(t.start) : 60;
      const s = Math.max(0, Math.min(1440 - Math.max(dur,SNAP), snap(top/HOUR*60)));
      t.date = c.dataset.date; t.start = toHM(s); t.end = toHM(s + dur);
      save(); render();
    });
  });
  // upuszczanie na pasek "cały dzień"
  main.querySelectorAll(".allday").forEach(c => {
    c.addEventListener("dblclick", e => { if(!e.target.closest(".chip")) openDialog(null, c.dataset.date); });
    c.addEventListener("dragover", e => { if(drag){ e.preventDefault(); c.classList.add("over"); } });
    c.addEventListener("dragleave", () => c.classList.remove("over"));
    c.addEventListener("drop", e => {
      e.preventDefault(); c.classList.remove("over");
      const t = drag && byId(drag.id); if(!t) return;
      t.date = c.dataset.date; t.start = ""; t.end = ""; save(); render();
    });
  });
  bindChips(main);
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
function openDialog(id, date, start){
  editing = id ? byId(id) : null;
  const preset = (!editing && filterPerson && filterPerson !== "__none") ? [filterPerson] : [];
  const t = editing || {title:"", date: date || iso(cur), start: start || "", end: start ? toHM(toMin(start)+60) : "", priority:1, done:false, notes:"", assignees: preset};
  document.getElementById("dlgTitle").textContent = editing ? "Edytuj zadanie" : "Nowe zadanie";
  fTitle.value = t.title; fDate.value = t.date; fPrio.value = t.priority;
  fStart.value = t.start; fEnd.value = t.end; fNotes.value = t.notes || ""; fDone.checked = !!t.done;
  fNewPerson.value = ""; drawPicker(t.assignees || []);
  document.getElementById("del").style.visibility = editing ? "visible" : "hidden";
  dlg.showModal(); fTitle.focus();
}
function drawPicker(selected){
  fPeople.innerHTML = people.length ? sortedPeople().map(p =>
    `<label><input type="checkbox" value="${esc(p.id)}"${selected.includes(p.id) ? " checked" : ""}> ${esc(p.name)}</label>`).join("")
    : `<span class="hint">Brak osób — dodaj poniżej lub w oknie „Osoby”.</span>`;
}
const pickedIds = () => [...fPeople.querySelectorAll("input:checked")].map(i => i.value);
function addPerson(name){
  name = name.trim().slice(0, 100); if(!name) return null;
  const known = people.find(p => p.name.toLowerCase() === name.toLowerCase());
  if(known) return known;
  const p = {id: uid(), name}; people.push(p); return p;
}
fAddPerson.onclick = () => {
  const keep = pickedIds(), p = addPerson(fNewPerson.value); if(!p) return;
  if(!keep.includes(p.id)) keep.push(p.id);
  fNewPerson.value = ""; drawPicker(keep); save(); fillPersonFilter();
};
fNewPerson.addEventListener("keydown", e => { if(e.key === "Enter"){ e.preventDefault(); fAddPerson.click(); } });
form.addEventListener("submit", e => {
  if(e.submitter && e.submitter.value !== "save") return;
  const t = editing || {id: uid()};
  t.title = fTitle.value.trim(); t.date = fDate.value; t.priority = +fPrio.value;
  t.start = fStart.value; t.end = fStart.value ? (fEnd.value || toHM(toMin(fStart.value)+60)) : "";
  if(t.end && toMin(t.end) <= toMin(t.start)) t.end = toHM(toMin(t.start)+SNAP);
  t.notes = fNotes.value; t.done = fDone.checked; t.assignees = pickedIds();
  if(!editing) tasks.push(t);
  save(); render();
});

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
// kolejność wykonania: data, potem godzina (zadania całodniowe najpierw), potem priorytet, potem tytuł
const byDue = (a,b) => a.date.localeCompare(b.date) || (a.start||"").localeCompare(b.start||"") || b.priority - a.priority || a.title.localeCompare(b.title);
function renderList(){
  const todayS = iso(new Date()), [from, to] = periodRange();
  let rows = visibleTasks();
  if(hideDone) rows = rows.filter(t => !t.done);
  if(listScope === "today") rows = rows.filter(t => t.date >= todayS);
  else if(listScope === "period") rows = rows.filter(t => t.date >= from && t.date <= to);
  rows.sort(byDue);
  const el = document.getElementById("list");
  let h = `<div class="list-head"><h2>Lista zadań (${rows.length})</h2>
    <label>Zakres <select id="lScope"><option value="all">Wszystkie</option><option value="today">Od dziś</option><option value="period">Widoczny okres</option></select></label>
    <label><input type="checkbox" id="lHide"> Ukryj wykonane</label></div>`;
  if(!rows.length) h += `<div class="empty">Brak zadań do wyświetlenia.</div>`;
  else {
    h += `<table class="tasks"><thead><tr><th></th><th>Termin</th><th>Zadanie</th><th>Osoby</th><th>Priorytet</th></tr></thead><tbody>`;
    let prev = "";
    for(const t of rows){
      const cls = ["trow", t.date !== prev && prev ? "newday" : "", t.date === todayS ? "istoday" : "", t.date < todayS && !t.done ? "late" : "", t.done ? "isdone" : ""].join(" ");
      prev = t.date;
      const when = fmtDate(t.date) + (t.start ? ` ${t.start}${t.end ? "–" + t.end : ""}` : " · cały dzień");
      h += `<tr class="${cls}" data-id="${esc(t.id)}"><td><input type="checkbox" data-done="${esc(t.id)}"${t.done ? " checked" : ""} aria-label="Wykonane"></td>` +
           `<td>${when}</td><td>${esc(t.title)}</td><td>${esc(namesOf(t).join(", "))}</td><td><span class="badge p${t.priority}">${["", "Niski", "Średni", "Wysoki"][t.priority]}</span></td></tr>`;
    }
    h += `</tbody></table>`;
  }
  el.innerHTML = h;
  lScope.value = listScope; lHide.checked = hideDone;
  lScope.onchange = () => { listScope = lScope.value; renderList(); };
  lHide.onchange = () => { hideDone = lHide.checked; renderList(); };
  el.querySelectorAll("tr.trow").forEach(r => r.addEventListener("click", e => { if(!e.target.matches("input")) openDialog(r.dataset.id); }));
  el.querySelectorAll("[data-done]").forEach(c => c.addEventListener("change", () => { const t = byId(c.dataset.done); if(t){ t.done = c.checked; save(); render(); } }));
}
document.getElementById("del").onclick = () => {
  if(editing && confirm("Usunąć to zadanie?")){ tasks = tasks.filter(t => t !== editing); save(); dlg.close(); render(); }
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
document.addEventListener("keydown", e => {
  if(dlg.open || pdlg.open || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
  if(e.key === "ArrowLeft") shift(-1); else if(e.key === "ArrowRight") shift(1);
  else if(e.key === "m") { view="month"; render(); } else if(e.key === "w") { view="week"; render(); } else if(e.key === "d") { view="day"; render(); }
});


/* ================= eksport / import ================= */
const closeMenu = () => { dataMenu.open = false; };
document.addEventListener("click", e => { if(!e.target.closest("#dataMenu")) closeMenu(); });
async function doExport(kind){
  closeMenu();
  try{
    if(DESKTOP){
      const name = await (kind === "xlsx" ? api().export_xlsx(currentData()) : api().export_json(currentData()));
      if(name) note("Wyeksportowano: " + name);
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
async function doImport(kind){
  closeMenu();
  if(!DESKTOP){ file.click(); return; }
  try{ const data = await (kind === "xlsx" ? api().import_xlsx() : api().import_json()); if(data) applyImport(data); }
  catch(e){ note("Import nie powiódł się: " + errText(e)); }
}
xlsExp.onclick = () => doExport("xlsx"); exp.onclick = () => doExport("json");
xlsImp.onclick = () => doImport("xlsx"); imp.onclick = () => doImport("json");
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
  document.getElementById("xlsExp").hidden = false; document.getElementById("xlsImp").hidden = false;
  api().get_version().then(v => { ver.textContent = "v" + v; }).catch(() => {});
  if(!updateChecked){ updateChecked = true; setTimeout(() => chk.click(), 2500); }
}

/* ================= start ================= */
function seed(){
  const t = iso(new Date()), a = {id:uid(), name:"Nowak Anna"}, b = {id:uid(), name:"Kowalski Jan"};
  return {people: [a, b], tasks: [
    {id:uid(), title:"Przykład: spotkanie zespołu", date:t, start:"10:00", end:"11:00", priority:2, done:false, notes:"", assignees:[a.id, b.id]},
    {id:uid(), title:"Przykład: zadanie na cały dzień", date:t, start:"", end:"", priority:1, done:false, notes:"", assignees:[]},
    {id:uid(), title:"Przykład: termin oddania raportu", date:iso(addDays(new Date(),2)), start:"15:30", end:"16:30", priority:3, done:false, notes:"", assignees:[a.id]}
  ]};
}
async function boot(){
  if(started) return; started = true;
  try{
    if(DESKTOP){
      const r = await api().load_state();
      view = (r.prefs && r.prefs.view) || "month";
      readOnly = !!r.readonly;                       // nie nadpisuj pliku, którego nie da się odczytać
      const d = r.tasks ? normalize({people: r.people, tasks: r.tasks}) : (readOnly ? {people: [], tasks: []} : seed());
      tasks = d.tasks; people = d.people;
      if(r.tasks === null && !readOnly) save();
      note(r.warning || "");
    } else {
      let d = null;
      try{ d = normalize(JSON.parse(localStorage.getItem(KEY))); }catch(e){}
      try{ view = localStorage.getItem(KEY + "_view") || "month"; }catch(e){}
      if(!d || !d.tasks.length) d = seed();
      tasks = d.tasks; people = d.people; save();
    }
  }catch(e){ readOnly = true; note("Nie udało się wczytać zadań: " + errText(e)); }
  render(); initUpdates();
}
if(DESKTOP){ if(api()) boot(); else window.addEventListener("pywebviewready", boot); } else boot();
setInterval(() => { if(started && view !== "month" && !dlg.open && !drag) render(); }, 5*60*1000);
