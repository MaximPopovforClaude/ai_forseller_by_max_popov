export type Shop = { id: number; name: string; title: string | null; workspace: string; role: string; marketplace?: "wb" | "ozon" | "ym" };
export type Tab = { key: string; title: string; group: string; help?: string };
export type Col = { field: string; title: string; type: string; group?: string; metric?: string; period?: string | null;
  stack?: { label: string; field: string; type: string; diff?: boolean }[] };
export type TabData = {
  key: string;
  sort?: { field: string; desc: boolean };       // сортировка по умолчанию (строки уже отсортированы сервером)
  title: string;
  columns: Col[];
  rows: Record<string, unknown>[];
  dangers?: { indicator: string; problem: string; hypothesis: string }[];   // Чек-лист: «Опасности»
  max_editor?: { nm_id: number; fields: { key: string; title: string; value: number | null; auto?: number | null }[] };
  cell_colors?: Record<string, Record<string, string>>;   // заливка текстовых ячеек по значению (ABC: A/B/C, рекомендации)
  rows_total?: number;      // большая таблица: всего строк (пришла часть)
  limit?: number;
  editable?: string;
  stale?: boolean;          // показан прошлый расчёт, свежий считается фоном
  cached_at?: string;
  layout?: string;
  col_layout?: [string, string, string][];
  col_hidden?: [string, string, string, number?][];
  periods?: string[];
  metrics?: string[];
  layout_editor?: string;
  switch?: { key: string; title: string; value: string; options: [string, string][] };
  form?: string;
  home?: boolean;
  ozon?: boolean; hint?: string;
  current?: Record<string, unknown>;
  regimes?: string[];
  heat?: string[][];
  custom?: "actions" | "prices" | "competitors" | "insights" | "planning" | "exclusions" | "staff" | "photos" | "rnp" | "news" | "entry" | "ext_costs" | "promo" | "hypotheses" | "seo" | "mrc" | "shelves";
  empty?: string;
  unit?: { p1_from: string; p1_to: string; p2_from: string; p2_to: string; per_unit: boolean };   // Юнитка: периоды, которые реально посчитаны
  total_row?: Record<string, unknown>;   // своя строка «ИТОГО» с бэкенда (доли — по формулам, а не суммой)
  rules?: Record<string, { gt: number | null; le: number | null; color: string }[]>;   // заливка по порогам (как в таблице)
  grad?: string[];        // заливка от максимума к минимуму, 0 не красим
  retry?: number | null;  // данные грузятся — перезапросить через N секунд
  plain?: boolean;        // без строки «ИТОГО» и графика (строки — разные периоды одного товара)
  note?: string | null;   // пояснение к данным вкладки (откуда взяты цифры)   // группы столбцов с заливкой «чем больше — тем зеленее» (min…max по группе)
  chart?: { x: string; series: { field: string; title: string; type: string; axis?: number }[] };
};
export type Invite = { id: string; email: string; role: string; shop_ids: number[] | null; expires_at: string };
export type Article = { nm_id: number; vendor_code: string | null; title: string | null; subject: string | null; photo: string | null; orders_30d: number; grp?: string | null };
export type Workspace = { id: number; name: string; role: string; plan: string };
export type Me = { user: { id: number; email: string; name: string | null; superadmin: boolean; google_email?: string | null }; default_shop: number | null; shops: (Shop & { workspace_id: number })[];
  workspaces: Workspace[]; tabs: Tab[]; oz_tabs: Tab[]; ym_tabs: Tab[]; hidden_tabs?: Record<string, string[]>; tabbar?: Record<string, string[]>; gsheet?: boolean; terms_need?: boolean; terms_version?: string; news_unread?: number };
export type Member = { id: number; email: string; name: string | null; role: string; shop_ids: number[] | null; last_login_at: string | null; is_active: boolean };
export type WorkspaceInfo = { id: number; name: string; created_at: string; role: string; role_title: string; roles: Record<string, string>;
  shops: { id: number; name: string; title: string | null; marketplace: string; is_active: boolean; created_at: string;
    token?: { exp: string | null; scopes: string[]; kind: string; seller_oid: number | null; roles?: string[]; read_only?: boolean } | null; token_at: string | null;
    ad_token?: { added_at: string; campaigns?: number; running?: number; client_id_tail?: string } | null;
    token_server: boolean; loaded: number; last_ok: string | null; load_total?: number }[];
  first_load_total: number; members: Member[] | null;
  plan: string; plan_changed_at: string | null; compare_fresh_days: number; plans: Record<string, { title: string; about: string; ready: boolean }>; can_set_plan: boolean };

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { credentials: "same-origin", ...init });
  if (r.status === 401) throw new Error("401");
  if (!r.ok) {
    const t = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(t.detail || r.statusText);
  }
  return r.json();
}

const J = (method: string, body?: unknown): RequestInit =>
  ({ method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

/** Простые запросы к новым разделам (пункт управления, конкуренты, оплата, админка). */
export const http = {
  get: <T,>(url: string) => req<T>(url),
  post: <T,>(url: string, body?: unknown) => req<T>(url, J("POST", body ?? {})),
  put: <T,>(url: string, body?: unknown) => req<T>(url, J("PUT", body ?? {})),
  del: <T,>(url: string) => req<T>(url, { method: "DELETE" }),
};

export type ShopStaff = { workspace_id: number; staff: { id: number; name: string; user_id: number | null; n: number }[];
  assign: Record<string, number>; me: number | null; can_edit: boolean };

export const api = {
  me: () => req<Me>("/api/me"),
  setTabbar: (mp: string, keys: string[]) => req<{ mp: string; keys: string[] }>("/api/me/tabbar", J("PUT", { mp, keys })),
  setHiddenTabs: (mp: string, keys: string[]) => req<{ mp: string; keys: string[] }>("/api/me/hidden_tabs", J("PUT", { mp, keys })),
  login: (email: string, password: string) =>
    req("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  logout: () => req("/api/auth/logout", { method: "POST" }),
  setPref: (shop: number, key: string, value: unknown) =>
    req(`/api/shops/${shop}/prefs/${key}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }) }),
  setTax: (shop: number, v: { regime: string; rate: number; vat_rate: number; vat_deduct_wb: number; cost_vat?: boolean; valid_from?: string }) =>
    req(`/api/shops/${shop}/tax`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }),
  setCost: (shop: number, nm_id: number, cost: number) =>
    req(`/api/shops/${shop}/cost`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nm_id, cost }) }),
  workspace: (id: number) => req<WorkspaceInfo>(`/api/workspaces/${id}`),
  renameWorkspace: (id: number, name: string) =>
    req(`/api/workspaces/${id}/name`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) }),
  setPlan: (id: number, plan: string) =>
    req(`/api/workspaces/${id}/plan`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan }) }),
  invites: (ws: number) => req<Invite[]>(`/api/workspaces/${ws}/invites`),
  addExistingMember: (ws: number, v: { email: string; role: string; shop_ids: number[] | null }) =>
    req<{ email: string; user_id: number }>(`/api/workspaces/${ws}/members`, J("POST", v)),
  invite: (ws: number, v: { email: string; role: string; shop_ids: number[] | null }) =>
    req<{ link: string; days: number }>(`/api/workspaces/${ws}/invites`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }),
  revokeInvite: (ws: number, id: string) => req(`/api/workspaces/${ws}/invites/${id}`, { method: "DELETE" }),
  setMember: (ws: number, uid: number, v: { role: string; shop_ids: number[] | null }) =>
    req(`/api/workspaces/${ws}/members/${uid}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }),
  removeMember: (ws: number, uid: number) => req(`/api/workspaces/${ws}/members/${uid}`, { method: "DELETE" }),
  inviteInfo: (tok: string) => req<{ email: string; workspace: string; role: string; has_account: boolean }>(`/api/invites/${tok}`),
  acceptInvite: (tok: string, password: string, name: string) =>
    req(`/api/invites/${tok}/accept`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password, name }) }),
  addShop: (ws: number, v: { title: string; token: string; marketplace: string; client_id?: string; ad_client_id?: string; ad_client_secret?: string }) =>
    req<{ ok: boolean; shop_id: number; first_load: boolean; warnings?: string[] }>(`/api/workspaces/${ws}/shops`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }),
  replaceToken: (shop: number, token: string) =>
    req<{ ok: boolean; warnings?: string[] }>(`/api/shops/${shop}/token`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) }),
  replaceAdToken: (shop: number, client_id: string, client_secret: string) =>
    req<{ ok: boolean; campaigns: number; running: number }>(`/api/shops/${shop}/ad_token`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client_id, client_secret }) }),
  magicInfo: (tok: string) => req<{ email: string; purpose: "set_password" | "login" }>(`/api/auth/magic/${tok}`),
  magicUse: (tok: string, password?: string) =>
    req(`/api/auth/magic/${tok}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) }),
  notify: () => req<{ connected: boolean; old_bot: boolean; assistant: boolean; daily: boolean; daily_time: string; alerts: boolean; ai: boolean; kinds: { key: string; title: string; on: boolean }[];
    daily_mine: boolean; is_staff: boolean; shops: { id: number; title: string; mp: string; workspace: string | null; on: boolean }[]; send_from: string; send_to: string; bot: string | null; link: string | null }>("/api/me/notify"),
  setNotify: (v: { daily: boolean; daily_time: string; alerts: boolean; ai: boolean; kinds?: Record<string, boolean>; send_from?: string; send_to?: string;
    daily_mine?: boolean; muted_shops?: number[] }) =>
    req("/api/me/notify", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) }),
  notifyTest: () => req<{ ok: boolean }>("/api/me/notify/test", { method: "POST" }),
  setDefaultShop: (shop_id: number | null) =>
    req(`/api/me/default_shop`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shop_id }) }),
  setGoogleEmail: (email: string) => req(`/api/me/google_email`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) }),
  renameMe: (name: string) => req(`/api/me/name`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) }),
  shopStaff: (shop: number) => req<ShopStaff>(`/api/shops/${shop}/staff`),
  articles: (shop: number) => req<Article[]>(`/api/shops/${shop}/articles`),
  groups: (shop: number) => req<{ key: string; title: string; kind: "own" | "card" }[]>(`/api/shops/${shop}/groups`),
  setGroup: (shop: number, nm_id: number, group_name: string) =>
    req(`/api/shops/${shop}/group`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nm_id, group_name }) }),
  tab: (shop: number, key: string, p: TabQ, signal?: AbortSignal) => req<TabData>(`/api/shops/${shop}/tab/${key}?${tabQ(p)}`, { signal }),
  /** Вкладка → новая Google Таблица (доступ на почту пользователя) */
  tabGsheet: (shop: number, key: string, p: TabQ, cols: string[]) => {
    const q = tabQ({ ...p, limit: undefined });
    if (cols.length) q.set("cols", cols.join(","));
    return req<{ url: string; shared: boolean; note: string | null }>(`/api/shops/${shop}/tab/${key}/gsheet?${q}`, { method: "POST" });
  },
  /** Ссылка на выгрузку вкладки в Excel: те же фильтры, все строки; cols — видимые столбцы по порядку */
  tabXlsx: (shop: number, key: string, p: TabQ, cols: string[]) => {
    const q = tabQ({ ...p, limit: undefined });
    if (cols.length) q.set("cols", cols.join(","));
    return `/api/shops/${shop}/tab/${key}/xlsx?${q}`;
  },
};

export type TabQ = { from: string; to: string; nm: string; group?: string; p1from?: string; p1to?: string; perUnit?: boolean; campaign?: string;
  limit?: number; sort?: string; desc?: boolean; staff?: number | null };

function tabQ(p: TabQ) {
    const q = new URLSearchParams({ date_from: p.from, date_to: p.to });
    if (p.group) q.set("group", p.group);
    if (p.p1from && p.p1to) { q.set("p1_from", p.p1from); q.set("p1_to", p.p1to); }
    if (p.perUnit) q.set("per_unit", "true");
    if (p.campaign) q.set("campaign", p.campaign);
    if (p.staff) q.set("staff", String(p.staff));         // фильтр «Менеджер» — его артикулы магазина
    if (p.nm.trim()) q.set("nm_ids", p.nm.replace(/\s+/g, ""));
    if (p.limit) q.set("limit", String(p.limit));          // большие таблицы — частями (сервер сортирует по всем строкам)
    if (p.sort) { q.set("sort", p.sort); if (p.desc) q.set("desc", "true"); }
    return q;
}
