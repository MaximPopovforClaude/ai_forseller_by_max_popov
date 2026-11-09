const $ = (id) => document.getElementById(id);
const workerError = () => ({ok: false, status: 0, data: {detail:
  "Фон плагина не отвечает. Откройте chrome://extensions, перезагрузите это расширение и снова откройте его окно."}});
const send = (m) => new Promise(resolve => {
  let finished = false;
  const done = value => { if (!finished) { finished = true; clearTimeout(timer); resolve(value); } };
  const timer = setTimeout(() => done(workerError()), 30000);
  try {
    chrome.runtime.sendMessage(m, response => {
      const error = chrome.runtime.lastError;
      done(error || !response || typeof response !== "object" ? workerError() : response);
    });
  } catch { done(workerError()); }
});
let whoSequence = 0;
async function who() {
  const seq = ++whoSequence;
  const r = await send({type: "api", path: "/api/plugin/me"});
  if (seq !== whoSequence) return;
  const el = $("who");
  if (r.ok && r.data && Array.isArray(r.data.shops)) {
    el.className = "ok";
    el.textContent = `Подключено: ${r.data.name || "пользователь"}. Магазины: ${r.data.shops.map(s => s.title || "").join(", ") || "нет"}`;
  } else {
    el.className = "err";
    el.textContent = typeof r.data?.detail === "string" ? r.data.detail
      : "Ответ сайта не похож на данные платформы. Проверьте адрес, указанный ниже, и скачайте плагин со своего сайта.";
  }
}
async function recState() {
  const s = await send({type: "rec_state"});
  $("recst").textContent = s.on ? `Идёт запись: ${s.n} запросов, ${s.min} мин.` : "";
}
$("save").onclick = async () => {
  const t = $("tok").value.trim();
  if (!t) return;
  $("save").disabled = true;
  try {
    await chrome.storage.local.set({token: t, token_origin: $("platform-host").textContent.trim()});
    $("tok").value = "";
    await who();
  } catch {
    $("who").className = "err";$("who").textContent = "Не удалось сохранить код в Chrome. Перезагрузите расширение.";
  } finally { $("save").disabled = false; }
};
$("out").onclick = async () => {
  ++whoSequence;
  await chrome.storage.local.remove(["token", "token_origin"]);await who();
};
$("rec").onclick = async () => {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  await send({type: "rec_start", page: tab?.url || ""});await recState();
};
$("stop").onclick = async () => {
  const r = await send({type: "rec_stop"});
  $("recst").className = r.ok ? "ok" : "err";
  $("recst").textContent = r.ok ? `Отправлено: ${r.data.n} запросов (запись №${r.data.id}). Спасибо!` : (r.data?.detail || "Запись не отправлена.");
};
$("now").onclick = async () => {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab || !/^https:\/\/seller\.wildberries\.ru\//.test(tab.url || "")) {
    $("nowst").textContent = "Откройте вкладку с кабинетом продавца WB (seller.wildberries.ru) и нажмите ещё раз.";return;
  }
  chrome.tabs.sendMessage(tab.id, {type: "entry_now"}, r => {
    $("nowst").textContent = chrome.runtime.lastError
      ? "Плагин ещё не встроен в эту вкладку — обновите страницу кабинета (F5) и нажмите ещё раз."
      : r?.busy ? "Скачивание уже идёт — ход виден внизу слева в кабинете."
      : r?.ok ? "Запустил — ход виден внизу слева в кабинете." : "Не удалось запустить скачивание. Обновите вкладку кабинета.";
  });
};
chrome.storage.local.get("entry_auto").then(x => {$("auto").checked = x.entry_auto !== false;}).catch(() => {});
$("auto").onchange = () => chrome.storage.local.set({entry_auto: $("auto").checked});
who();recState();
