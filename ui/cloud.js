/* ===== Synchronizacja z OneDrive (tylko wersja PWA / przeglądarkowa) =====
   Logowanie: OAuth 2.0 (kod autoryzacji + PKCE) bez zewnętrznych bibliotek. Pliki: Microsoft Graph.
   Kalendarz grupowy używa tego samego formatu pliku i tego samego scalania zmian co program na Windows,
   więc komputer może wskazać ten sam plik (folder OneDrive) jako plik grupowy. */
(function(){
"use strict";
if(window.__DESKTOP__) return;
const CK = KEY + "_cloud", TK = KEY + "_cloudtok", PK = KEY + "_cloudpkce", BK = KEY + "_cloudbase_";
const AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0/";
const GRAPH = "https://graph.microsoft.com/v1.0/me/drive/root:/";
const SCOPE = "Files.ReadWrite offline_access";
const FIELDS = [["title"], ["date", "end_date", "start", "end"], ["priority"], ["status", "progress"], ["notes"], ["color"], ["assignees"], ["series"]];
const jget = (k, d) => { try{ const v = JSON.parse(localStorage.getItem(k)); return v == null ? d : v; }catch(e){ return d; } };
const jset = (k, v) => { try{ localStorage.setItem(k, JSON.stringify(v)); }catch(e){} };
let cfg = Object.assign({clientId: "", groupPath: "TaskListAK/grupowy.json", localPath: "TaskListAK/prywatny.json"}, jget(CK, {}));
if(cfg.localPath === "TaskListAK/lokalny.json") cfg.localPath = "TaskListAK/prywatny.json";
let busy = false, timer = null, status = "", lastOk = "";
const redirectUri = () => location.origin + location.pathname;

/* ---------- logowanie ---------- */
const b64u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const rnd = n => b64u(crypto.getRandomValues(new Uint8Array(n)));
async function login(){
  if(!cfg.clientId) throw new Error("Wpisz Client ID aplikacji (Microsoft Entra).");
  const verifier = rnd(48), state = rnd(12);
  const challenge = b64u(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  jset(PK, {verifier, state});
  const q = new URLSearchParams({client_id: cfg.clientId, response_type: "code", redirect_uri: redirectUri(), response_mode: "query",
    scope: SCOPE, state, code_challenge: challenge, code_challenge_method: "S256", prompt: "select_account"});
  location.href = AUTH + "authorize?" + q;
}
async function token(body){
  const r = await fetch(AUTH + "token", {method: "POST", headers: {"Content-Type": "application/x-www-form-urlencoded"}, body: new URLSearchParams(body)});
  const j = await r.json().catch(() => ({}));
  if(!r.ok) throw new Error(j.error_description ? j.error_description.split("\r")[0] : "Logowanie nie powiodło się (" + r.status + ").");
  jset(TK, {access: j.access_token, refresh: j.refresh_token || (jget(TK, {}).refresh || ""), exp: Date.now() + (j.expires_in - 60) * 1000});
}
async function finishLogin(){
  const p = new URLSearchParams(location.search);
  if(!p.has("code") && !p.has("error")) return;
  const pk = jget(PK, {});
  history.replaceState(null, "", location.pathname);
  if(p.has("error")){ status = "Logowanie przerwane: " + (p.get("error_description") || p.get("error")); return; }
  if(!pk.state || p.get("state") !== pk.state){ status = "Logowanie odrzucone (zły parametr state)."; return; }
  try{
    await token({client_id: cfg.clientId, grant_type: "authorization_code", code: p.get("code"), redirect_uri: redirectUri(), code_verifier: pk.verifier, scope: SCOPE});
    jset(PK, {}); status = "Zalogowano.";
  }catch(e){ status = e.message; }
}
async function access(){
  const t = jget(TK, {});
  if(t.access && t.exp > Date.now()) return t.access;
  if(!t.refresh) throw Object.assign(new Error("Zaloguj się do OneDrive."), {needLogin: true});
  try{ await token({client_id: cfg.clientId, grant_type: "refresh_token", refresh_token: t.refresh, scope: SCOPE}); }
  catch(e){ jset(TK, {}); throw Object.assign(new Error("Sesja wygasła — zaloguj się ponownie."), {needLogin: true}); }
  return jget(TK, {}).access;
}
const loggedIn = () => { const t = jget(TK, {}); return !!(t.access || t.refresh); };

/* ---------- Graph: odczyt i zapis pliku ---------- */
const enc = path => path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
async function gfetch(url, opt){
  const r = await fetch(url, Object.assign({}, opt, {headers: Object.assign({Authorization: "Bearer " + await access()}, opt && opt.headers)}));
  if(r.status === 401){ jset(TK, {}); throw Object.assign(new Error("Sesja wygasła — zaloguj się ponownie."), {needLogin: true}); }
  return r;
}
async function readRemote(path){                       // {doc, etag} albo null, gdy pliku jeszcze nie ma
  const m = await gfetch(GRAPH + enc(path) + "?select=eTag,size");
  if(m.status === 404) return null;
  if(!m.ok) throw new Error("OneDrive: błąd odczytu (" + m.status + ").");
  const meta = await m.json();
  const c = await gfetch(GRAPH + enc(path) + ":/content");
  if(!c.ok) throw new Error("OneDrive: błąd pobierania pliku (" + c.status + ").");
  let doc; try{ doc = JSON.parse((await c.text()).replace(/^﻿/, "")); }catch(e){ throw new Error("Plik w OneDrive nie jest poprawnym JSON."); }
  if(Array.isArray(doc)) doc = {people: [], tasks: doc};
  if(!doc || !Array.isArray(doc.tasks)) throw new Error("Plik w OneDrive nie jest kalendarzem.");
  return {doc: {people: Array.isArray(doc.people) ? doc.people : [], tasks: doc.tasks}, etag: meta.eTag};
}
async function writeRemote(path, doc, etag){            // false = ktoś zapisał w międzyczasie (412)
  const r = await gfetch(GRAPH + enc(path) + ":/content", {method: "PUT", headers: Object.assign({"Content-Type": "application/json"}, etag ? {"If-Match": etag} : {}),
    body: JSON.stringify(doc, null, 1)});
  if(r.status === 412) return false;
  if(!r.ok) throw new Error("OneDrive: zapis nie powiódł się (" + r.status + ").");
  return true;
}

/* ---------- scalanie (to samo co merge_group w main.py) ---------- */
const calOf = t => t.calendar === "group" ? "group" : "local";
function part(cal){
  const ts = tasks.filter(t => calOf(t) === cal), used = new Set(ts.flatMap(t => t.assignees || []));
  return {people: cal === "local" ? people.slice() : people.filter(p => used.has(p.id)), tasks: ts};
}
function norm(p){
  const names = Object.fromEntries(p.people.map(x => [x.id, x.name])), out = new Map();
  for(const t of p.tasks){
    const d = {}; for(const k of ["title", "date", "end_date", "start", "end", "priority", "status", "progress", "notes", "color", "series"]) d[k] = t[k] == null ? "" : t[k];
    d.end_date = d.end_date || d.date;
    d.assignees = (t.assignees || []).map(a => names[a]).filter(Boolean).sort();
    out.set(t.id, d);
  }
  return out;
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const sorted = p => [...norm(p)].sort((x, y) => x[0] < y[0] ? -1 : 1);
function merge(base, mine, theirs, cal){
  const b = base ? norm(base) : null, m = norm(mine), t = norm(theirs), out = new Map(), rep = {added: 0, changed: 0, removed: 0};
  for(const tid of [...m.keys(), ...[...t.keys()].filter(x => !m.has(x))]){
    const inm = m.has(tid), int_ = t.has(tid), inb = !!b && b.has(tid);
    if(inm && int_){
      const bt = inb ? b.get(tid) : null, res = Object.assign({}, m.get(tid));
      for(const g of FIELDS){
        const mv = g.map(k => m.get(tid)[k]), tv = g.map(k => t.get(tid)[k]);
        if(same(mv, tv)) continue;
        if(bt && same(mv, g.map(k => bt[k]))){ g.forEach(k => { res[k] = t.get(tid)[k]; }); }
      }
      out.set(tid, res); if(!same(res, m.get(tid))) rep.changed++;
    }else if(inm){
      if(inb && same(m.get(tid), b.get(tid))) rep.removed++; else out.set(tid, m.get(tid));
    }else{
      if(inb && same(t.get(tid), b.get(tid))) continue;
      out.set(tid, t.get(tid)); if(!inb) rep.added++;
    }
  }
  // z powrotem do postaci {people, tasks}: osoby łączone po nazwie
  const pid = {}; for(const p of theirs.people) pid[p.name] = p.id; for(const p of mine.people) pid[p.name] = p.id;
  const full = new Map(mine.tasks.map(x => [x.id, x])); for(const x of theirs.tasks) if(!full.has(x.id)) full.set(x.id, x);
  let usedNames = [...new Set([...out.values()].flatMap(d => d.assignees))].sort();
  if(cal === "local") usedNames = [...new Set([...usedNames, ...mine.people.map(p => p.name), ...theirs.people.map(p => p.name)])].sort();   // prywatny: wspólna lista osób, także bez zadań
  const ppl = usedNames.map(n => ({id: pid[n] || uid(), name: n})), idOf = Object.fromEntries(ppl.map(p => [p.name, p.id]));
  const list = [...out].map(([id, d]) => Object.assign({}, full.get(id), d, {id, calendar: cal, assignees: d.assignees.map(n => idOf[n])}));
  list.sort((x, y) => (x.date + x.start + x.title.toLowerCase() + x.id).localeCompare(y.date + y.start + y.title.toLowerCase() + y.id));
  return {merged: {people: ppl, tasks: list}, rep};
}
function applyMerged(cal, merged){                      // wstaw wynik do programu (osoby po nazwie), zachowując drugi kalendarz
  const kept = tasks.filter(t => calOf(t) !== cal), byName = new Map(), ids = new Set();
  const pp = people.slice(); pp.forEach(p => { byName.set(p.name.toLowerCase(), p.id); ids.add(p.id); });
  const map = {};
  for(const p of merged.people){
    const k = p.name.toLowerCase();
    if(!byName.has(k)){ const id = ids.has(p.id) ? uid() : p.id; pp.push({id, name: p.name}); byName.set(k, id); ids.add(id); }
    map[p.id] = byName.get(k);
  }
  const taken = new Set(kept.map(t => t.id)), add = [];
  for(const t of merged.tasks){
    const o = fixTask(Object.assign({}, t, {assignees: (t.assignees || []).map(a => map[a]).filter(Boolean), calendar: cal}));
    if(taken.has(o.id)) o.id = uid(); taken.add(o.id); add.push(o);
  }
  tasks = kept.concat(add); people = pp;
}

/* ---------- synchronizacja jednego kalendarza ---------- */
async function syncCal(cal, path){
  let notes = "";
  for(let i = 0; i < 4; i++){
    const mine = part(cal), remote = await readRemote(path), theirs = remote ? remote.doc : {people: [], tasks: []};
    const clean = {people: theirs.people.filter(p => p && p.id && p.name), tasks: theirs.tasks.map(t => Object.assign({}, t, {calendar: cal}))};
    const {merged, rep} = merge(jget(BK + cal, null), mine, clean, cal);
    const mergedDoc = {people: merged.people, tasks: merged.tasks.map(t => Object.assign({}, t))};
    if(!same(sorted(mergedDoc), sorted(clean))){
      const ok = await writeRemote(path, mergedDoc, remote && remote.etag);
      if(!ok) continue;                                // ktoś zapisał w międzyczasie: scal jeszcze raz
    }
    if(!same(sorted(mergedDoc), sorted(mine))){
      applyMerged(cal, mergedDoc); window.__cloudApply = true; try{ render(); }finally{ window.__cloudApply = false; }
      notes = [rep.added && ("nowe: " + rep.added), rep.changed && ("zmienione: " + rep.changed), rep.removed && ("usunięte: " + rep.removed)].filter(Boolean).join(", ") || "zmiany";
    }
    jset(BK + cal, mergedDoc);
    return notes;
  }
  throw new Error("Plik w OneDrive jest zmieniany przez innych — spróbuj za chwilę.");
}
async function syncAll(manual){
  if(busy || !cfg.clientId || !loggedIn() || !started) return;
  busy = true; setStatus("Synchronizacja…");
  try{
    const r = [];
    if(cfg.groupPath) r.push(await syncCal("group", cfg.groupPath));
    if(cfg.localPath) r.push(await syncCal("local", cfg.localPath));
    if(r.some(Boolean)){ origSave(); note("OneDrive — " + r.filter(Boolean).join("; ") + ".", true); }
    lastOk = new Date().toLocaleTimeString("pl-PL", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    setStatus("Zsynchronizowano o " + lastOk + ".");
  }catch(e){
    setStatus(e.message || String(e));
    if(manual || e.needLogin) note("OneDrive: " + (e.message || e));
  }finally{ busy = false; }
}
function schedule(ms){ clearTimeout(timer); timer = setTimeout(() => syncAll(false), ms || 3000); }

/* ---------- podłączenie do programu ---------- */
const origSave = save;
save = function(){ origSave(); if(!window.__cloudApply) schedule(3000); };
setInterval(() => syncAll(false), 60000);
window.addEventListener("focus", () => schedule(800));
document.addEventListener("visibilitychange", () => { if(!document.hidden) schedule(800); });

/* ---------- okno ustawień ---------- */
const btn = document.createElement("button");
btn.className = "btn snav"; btn.id = "cloudBtn"; btn.type = "button"; btn.setAttribute("aria-haspopup", "dialog");
btn.innerHTML = '<i data-ic="folder"></i>OneDrive';
const anchor = document.getElementById("dataBtn"); if(anchor) anchor.insertAdjacentElement("afterend", btn);
const dlgC = document.createElement("dialog"); dlgC.className = "fdlg"; dlgC.id = "clouddlg";
dlgC.innerHTML = `<form method="dialog"><h2>Synchronizacja z OneDrive</h2><div class="fdbody">
<p class="hint">Zadania są zapisywane w plikach JSON w Twoim OneDrive i scalane ze zmianami z innych urządzeń. Wymagany jest Client ID aplikacji zarejestrowanej w Microsoft Entra (instrukcja: INSTRUKCJA_PWA.md w repozytorium).</p>
<label>Client ID aplikacji</label><input type="text" id="cdId" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
<label>Plik kalendarza grupowego (w OneDrive)</label><input type="text" id="cdGroup" autocomplete="off" autocapitalize="off" spellcheck="false">
<label>Plik kalendarza prywatnego (ten sam co na komputerze; puste = tylko na tym telefonie)</label><input type="text" id="cdLocal" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="TaskListAK/prywatny.json">
<p class="hint">Adres powrotu do wpisania w Entra: <code id="cdUri"></code></p>
<p id="cdStatus" role="status"></p></div>
<div class="actions"><button class="btn primary" type="button" id="cdLogin">Zaloguj</button><button class="btn" type="button" id="cdSync">Synchronizuj teraz</button><button class="btn" type="button" id="cdOut">Wyloguj</button><button class="btn" type="submit" id="cdClose">Zamknij</button></div></form>`;
document.body.appendChild(dlgC);
const $ = id => document.getElementById(id);
function setStatus(s){ status = s; const el = $("cdStatus"); if(el) el.textContent = s || (loggedIn() ? "Zalogowano." : "Nie zalogowano."); }
function readForm(){ cfg = {clientId: $("cdId").value.trim(), groupPath: $("cdGroup").value.trim().replace(/^\/+/, ""), localPath: $("cdLocal").value.trim().replace(/^\/+/, "")}; jset(CK, cfg); }
btn.onclick = () => {
  $("cdId").value = cfg.clientId; $("cdGroup").value = cfg.groupPath; $("cdLocal").value = cfg.localPath; $("cdUri").textContent = redirectUri();
  setStatus(status); dlgC.showModal();
};
$("cdLogin").onclick = async () => { readForm(); try{ await login(); }catch(e){ setStatus(e.message); } };
$("cdSync").onclick = () => { readForm(); if(!loggedIn()) setStatus("Najpierw się zaloguj."); else syncAll(true); };
$("cdOut").onclick = () => { jset(TK, {}); try{ localStorage.removeItem(BK + "group"); localStorage.removeItem(BK + "local"); }catch(e){} setStatus("Wylogowano."); };
dlgC.addEventListener("close", readForm);
btn.querySelectorAll("[data-ic]").forEach(e => { e.innerHTML = ic(e.dataset.ic); });

/* ---------- start ---------- */
(async () => {
  await finishLogin();
  if(status && !$("cdStatus").textContent) setStatus(status);
  if(!cfg.clientId){ setStatus(""); return; }
  if(status.startsWith("Zalogowano") || status.startsWith("Logowanie")){ btn.click(); }
  schedule(2500);
})();
})();
