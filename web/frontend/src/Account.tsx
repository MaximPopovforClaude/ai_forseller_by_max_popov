import { useEffect, useState } from "react";
import { api, http, type Me, type WorkspaceInfo } from "./api";
import type { Page } from "./Sidebar";
import { Members } from "./Members";
import { Shops } from "./Shops";
import { Notify } from "./Notify";
import { HiggsfieldConnect, SecretKey } from "./WildboxKey";
import { PluginBox } from "./Plugin";

const dt = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—");

export function Account({ me, wsId, page, onChanged }: { me: Me; wsId: number; page: Page; onChanged: () => void }) {
  const [w, setW] = useState<WorkspaceInfo | null>(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [wsName, setWsName] = useState("");
  const [myName, setMyName] = useState(me.user.name || "");
  const [gmail, setGmail] = useState(me.user.google_email || "");
  const load = () => api.workspace(wsId).then((x) => { setW(x); setWsName(x.name); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [wsId]);
  if (err) return <div className="err">{err}</div>;
  if (!w) return <div className="hint">Загрузка…</div>;
  const isAdmin = w.role === "owner" || w.role === "admin";
  const saved = (m: string) => { setOk(m); setErr(""); setTimeout(() => setOk(""), 2500); onChanged(); load(); };

  if (page === "members") return (
    <div className="acc">
      <h2>Пользователи и права · {w.name}</h2>
      <Members w={w} reload={load} />
      <div className="acc-box">
        <b>Уровни доступа</b>
        <ul>
          <li><b>Владелец</b> — всё, включая доступы других людей и удаление кабинета.</li>
          <li><b>Админ</b> — магазины, токены, СНО, доступы (кроме владельца).</li>
          <li><b>Редактор</b> — ручные данные: себестоимость, налоги, расходы, группы артикулов.</li>
          <li><b>Просмотр</b> — только смотреть таблицы и графики.</li>
        </ul>
        Доступ можно дать ко всему кабинету или только к выбранным магазинам. Все изменения доступа пишутся в журнал.
      </div>
    </div>
  );

  return (
    <div className="acc">
      <h2>Настройки аккаунта</h2>
      {ok && <div className="ok">{ok}</div>}
      <div className="acc-box">
        <b>Профиль</b>
        <div className="acc-row"><span>Логин</span>{me.user.email}</div>
        <div className="acc-row"><span>Имя</span>
          <input value={myName} onChange={(e) => setMyName(e.target.value)} placeholder="Как к вам обращаться" />
          <button onClick={() => api.renameMe(myName).then(() => saved("Имя сохранено")).catch((e) => setErr(e.message))}>Сохранить</button>
        </div>
        <div className="acc-row" title="На эту почту выдаётся доступ к выгрузкам «📗 Google Таблица». Пусто — почта входа"><span>Почта Google</span>
          <input value={gmail} onChange={(e) => setGmail(e.target.value)} placeholder={me.user.email} type="email" />
          <button onClick={() => api.setGoogleEmail(gmail).then(() => saved("Почта Google сохранена")).catch((e) => setErr(e.message))}>Сохранить</button>
          <span className="hint">для Google Таблиц — если вход на сайт не через Google-почту</span>
        </div>
      </div>
      {me.shops.length > 1 && (
        <div className="acc-box">
          <b>Магазин по умолчанию</b>
          <div className="acc-row"><span>Открывать</span>
            <select value={me.default_shop ?? ""} onChange={(e) => api.setDefaultShop(e.target.value ? Number(e.target.value) : null)
              .then(() => saved("Магазин по умолчанию сохранён")).catch((x) => setErr(x.message))}>
              <option value="">первый в списке</option>
              {me.shops.map((s) => <option key={s.id} value={s.id}>{s.title || s.name}</option>)}
            </select>
          </div>
          <div className="hint">Он будет первым в списке магазинов и откроется при входе.</div>
        </div>
      )}
      <div className="acc-box">
        <b>Кабинет</b>
        <div className="acc-row"><span>Название</span>
          {isAdmin ? <>
            <input value={wsName} onChange={(e) => setWsName(e.target.value)} />
            <button onClick={() => api.renameWorkspace(w.id, wsName).then(() => saved("Название сохранено")).catch((e) => setErr(e.message))}>Сохранить</button>
          </> : w.name}
        </div>
        <div className="acc-row"><span>Ваша роль</span>{w.role_title}</div>
        <div className="acc-row"><span>Создан</span>{dt(w.created_at)}</div>
      </div>
      <div className="acc-box">
        <b>Тариф</b>
        <div className="acc-row"><span>Сейчас</span>{w.plans[w.plan]?.title || w.plan}</div>
        <div className="hint">Сменить тариф, оплатить, ввести промокод — в разделе «Тариф и оплата» (меню слева).</div>
      </div>
      <Shops w={w} reload={load} onShopsChanged={onChanged} />
      <SecretKey wsId={w.id} kind="wildbox" />
      <SecretKey wsId={w.id} kind="claude" />
      <div className="acc-box">
        <b>🔌 Свои нейросети и ассистенты (MCP)</b>
        <div className="hint">В дополнение к тарифу: подключите свою Claude (claude.ai, Claude Code, ассистента на своём сервере), ChatGPT, Gemini
          и другие к данным платформы — с правами на каждое подключение. Стометрик продолжает работать как раньше.</div>
        <button onClick={() => window.dispatchEvent(new CustomEvent("ais:page", { detail: "ai" }))}>Открыть «Нейросети (MCP)» → ＋ Новый токен</button>
      </div>
      <PluginBox key={w.id} wsId={w.id} wsName={w.name} />
      <HiggsfieldConnect wsId={w.id} />
      <SecretKey key={`openai-images-${w.id}`} wsId={w.id} kind="openai_images" />
      <div className="acc-box">
        <b>Сводка ИИ на главной</b>
        <div className="acc-row"><span>Сравнения карточек</span>учитывать загруженные за последние
          {isAdmin ? <input className="w60" type="number" min={1} max={90} defaultValue={w.compare_fresh_days}
            onBlur={(e) => http.put(`/api/workspaces/${w.id}/compare_fresh`, { days: Number(e.target.value) }).then(() => saved("Сохранено")).catch((x) => setErr(x.message))} />
            : <b> {w.compare_fresh_days} </b>} дн.</div>
        <div className="hint">Если вы загрузили отчёт WB «Сравнение карточек» с артикулом магазина, его ИИ-разбор показывается в сводке ИИ на главной, пока сравнение свежее.</div>
      </div>
      <Notify />
    </div>
  );
}
