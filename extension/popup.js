const $ = (id) => document.getElementById(id);
const send = (m) => new Promise((r) => chrome.runtime.sendMessage(m, r));

async function who() {
  const r = await send({ type: "api", path: "/api/plugin/me" });
  const el = $("who");
  if (r.ok) {
    el.className = "ok";
    el.textContent = `Подключено: ${r.data.name}. Магазины: ${r.data.shops.map((s) => s.title).join(", ") || "нет"}`;
  } else {
    el.className = r.status ? "err" : "hint";
    el.textContent = (r.data && r.data.detail) || `Ошибка ${r.status}`;
  }
}
async function recState() {
  const s = await send({ type: "rec_state" });
  $("recst").textContent = s.on ? `Идёт запись: ${s.n} запросов, ${s.min} мин.` : "";
}
$("save").onclick = async () => {
  const t = $("tok").value.trim();
  if (!t) return;
  await chrome.storage.local.set({ token: t });
  $("tok").value = "";
  who();
};
$("out").onclick = async () => { await chrome.storage.local.remove("token"); who(); };
$("rec").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await send({ type: "rec_start", page: (tab && tab.url) || "" });
  recState();
};
$("stop").onclick = async () => {
  const r = await send({ type: "rec_stop" });
  $("recst").className = r.ok ? "ok" : "err";
  $("recst").textContent = r.ok ? `Отправлено: ${r.data.n} запросов (запись №${r.data.id}). Спасибо!` : ((r.data && r.data.detail) || `Ошибка ${r.status}`);
};
$("now").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https:\/\/seller\.wildberries\.ru\//.test(tab.url || "")) {
    $("nowst").textContent = "Откройте вкладку с кабинетом продавца WB (seller.wildberries.ru) и нажмите ещё раз.";
    return;
  }
  chrome.tabs.sendMessage(tab.id, { type: "entry_now" }, r => {
    $("nowst").textContent = chrome.runtime.lastError
      ? "Плагин ещё не встроен в эту вкладку — обновите страницу кабинета (F5) и нажмите ещё раз."
      : r?.busy ? "Скачивание уже идёт — ход виден внизу слева в кабинете."
      : r?.ok ? "Запустил — ход виден внизу слева в кабинете." : "Не удалось запустить скачивание. Обновите вкладку кабинета.";
  });
};
chrome.storage.local.get("entry_auto").then((x) => { $("auto").checked = x.entry_auto !== false; });
$("auto").onchange = () => chrome.storage.local.set({ entry_auto: $("auto").checked });
who(); recState();
