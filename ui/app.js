"use strict";
const KEY = "tasklist_ak_v1";      // klucz localStorage (tylko gdy uruchomiono w zwykłej przeglądarce)
const DESKTOP = !!window.__DESKTOP__;
const HOUR = 48;                 // px na godzinę
const SNAP = 15;                 // minuty
const MONTHS = ["styczeń","luty","marzec","kwiecień","maj","czerwiec","lipiec","sierpień","wrzesień","październik","listopad","grudzień"];
const DOW = ["Pon","Wt","Śr","Czw","Pt","Sob","Nd"];


let tasks = [];
let view = "month";
let cur = new Date(); cur.setHours(0,0,0,0);
let drag = null;                 // {id, offY}
let started = false, readOnly = false, saveTimer = null, chain = Promise.resolve();
const api = () => window.pywebview && window.pywebview.api;
const errText = e => (e && (e.message || e.toString())) || "nieznany błąd";
function note(msg){ const el = document.getElementById("note"); el.textContent = msg || ""; el.hidden = !msg; }

/* ---- zapis: w aplikacji do pliku w %LOCALAPPDATA%\TaskListAK, w przeglądarce do localStorage ---- */
function save(){
  if(!DESKTOP){ try{ localStorage.setItem(KEY, JSON.stringify(tasks)); }catch(e){} return; }
  if(readOnly) return;
  clearTimeout(saveTimer); saveTimer = setTimeout(flush, 150);
}
function flush(){
  clearTimeout(saveTimer);
  if(!DESKTOP || readOnly) return chain;
  const snap = JSON.parse(JSON.stringify(tasks));
  chain = chain.then(() => api().save_tasks(snap)).then(() => note("")).catch(e => note("Zapis nie powiódł się: " + errText(e)));
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
const tasksOn = ds => tasks.filter(t => t.date === ds).sort(byTime);

/* ================= render ================= */
function render(){
  document.querySelectorAll("#views .btn").forEach(b => b.classList.toggle("active", b.dataset.v === view));
  const main = document.getElementById("main");
  if(view === "month") renderMonth(main); else renderTimeGrid(main, view === "week");
  saveView();
}

function setTitle(s){ document.getElementById("title").textContent = s; }

function chipHTML(t){
  const time = t.start ? t.start + " " : "";
  return `<span class="chip p${t.priority}${t.done?" done":""}" draggable="true" data-id="${t.id}" title="${esc(t.title)}">${time}${esc(t.title)}</span>`;
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
             `${esc(t.title)}<small>${t.start}–${toHM(ev.e)}</small><span class="rz" data-rz="${t.id}"></span></div>`;
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
  const t = editing || {title:"", date: date || iso(cur), start: start || "", end: start ? toHM(toMin(start)+60) : "", priority:1, done:false, notes:""};
  document.getElementById("dlgTitle").textContent = editing ? "Edytuj zadanie" : "Nowe zadanie";
  fTitle.value = t.title; fDate.value = t.date; fPrio.value = t.priority;
  fStart.value = t.start; fEnd.value = t.end; fNotes.value = t.notes || ""; fDone.checked = !!t.done;
  document.getElementById("del").style.visibility = editing ? "visible" : "hidden";
  dlg.showModal(); fTitle.focus();
}
form.addEventListener("submit", e => {
  if(e.submitter && e.submitter.value !== "save") return;
  const t = editing || {id: uid()};
  t.title = fTitle.value.trim(); t.date = fDate.value; t.priority = +fPrio.value;
  t.start = fStart.value; t.end = fStart.value ? (fEnd.value || toHM(toMin(fStart.value)+60)) : "";
  if(t.end && toMin(t.end) <= toMin(t.start)) t.end = toHM(toMin(t.start)+SNAP);
  t.notes = fNotes.value; t.done = fDone.checked;
  if(!editing) tasks.push(t);
  save(); render();
});
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
  if(dlg.open || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
  if(e.key === "ArrowLeft") shift(-1); else if(e.key === "ArrowRight") shift(1);
  else if(e.key === "m") { view="month"; render(); } else if(e.key === "w") { view="week"; render(); } else if(e.key === "d") { view="day"; render(); }
});


/* ================= eksport / import ================= */
exp.onclick = async () => {
  try{
    if(DESKTOP){ const name = await api().export_tasks(tasks); if(name) note("Wyeksportowano: " + name); return; }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(tasks, null, 2)], {type:"application/json"}));
    a.download = `tasklist-${iso(new Date())}.json`; a.click(); URL.revokeObjectURL(a.href);
  }catch(e){ note("Eksport nie powiódł się: " + errText(e)); }
};
async function applyImport(data){
  if(confirm(`Zaimportować ${data.length} zadań? Obecne zadania zostaną zastąpione.`)){ tasks = data; save(); render(); }
}
imp.onclick = async () => {
  if(!DESKTOP){ file.click(); return; }
  try{ const data = await api().import_tasks(); if(data) await applyImport(data); }
  catch(e){ note("Import nie powiódł się: " + errText(e)); }
};
file.onchange = async () => {
  try{
    const data = JSON.parse(await file.files[0].text());
    if(!Array.isArray(data)) throw 0;
    await applyImport(data);
  }catch(e){ alert("Nieprawidłowy plik JSON."); }
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
  api().get_version().then(v => { ver.textContent = "v" + v; }).catch(() => {});
  if(!updateChecked){ updateChecked = true; setTimeout(() => chk.click(), 2500); }
}

/* ================= start ================= */
function seed(){
  const t = iso(new Date());
  return [
    {id:uid(), title:"Przykład: spotkanie zespołu", date:t, start:"10:00", end:"11:00", priority:2, done:false, notes:""},
    {id:uid(), title:"Przykład: zadanie na cały dzień", date:t, start:"", end:"", priority:1, done:false, notes:""},
    {id:uid(), title:"Przykład: termin oddania raportu", date:iso(addDays(new Date(),2)), start:"15:30", end:"16:30", priority:3, done:false, notes:""}
  ];
}
async function boot(){
  if(started) return; started = true;
  try{
    if(DESKTOP){
      const r = await api().load_state();
      view = (r.prefs && r.prefs.view) || "month";
      readOnly = !!r.readonly;                       // nie nadpisuj pliku, którego nie da się odczytać
      tasks = r.tasks || (readOnly ? [] : seed());
      if(r.tasks === null && !readOnly) save();
      note(r.warning || "");
    } else {
      try{ tasks = JSON.parse(localStorage.getItem(KEY)) || []; }catch(e){ tasks = []; }
      try{ view = localStorage.getItem(KEY + "_view") || "month"; }catch(e){}
      if(!tasks.length){ tasks = seed(); save(); }
    }
  }catch(e){ readOnly = true; note("Nie udało się wczytać zadań: " + errText(e)); }
  render(); initUpdates();
}
if(DESKTOP){ if(api()) boot(); else window.addEventListener("pywebviewready", boot); } else boot();
setInterval(() => { if(started && view !== "month" && !dlg.open && !drag) render(); }, 5*60*1000);
