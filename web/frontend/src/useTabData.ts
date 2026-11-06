import { useEffect, useRef, useState } from "react";
import { api, type TabData, type TabQ } from "./api";

type Result = { key: string; viewKey: string; data: TabData | null; error: string; loading: boolean };

/** A response belongs to one shop, tab and set of filters, including during navigation. */
export function useTabData(shop: number | null, tab: string, query: TabQ, enabled: boolean, reload: number) {
  const key = JSON.stringify([enabled, shop, tab, query]);
  // Pagination/sorting may keep the same table under its loading overlay, so AG
  // Grid does not lose its sort when columns disappear. Actual filters still hide it.
  const viewKey = JSON.stringify([enabled, shop, tab, { ...query, limit: undefined, sort: undefined, desc: undefined }]);
  const current = useRef(key);
  current.current = key;
  const [result, setResult] = useState<Result | null>(null);
  useEffect(() => {
    if (!enabled || !shop) return;
    let live = true;
    const controller = new AbortController();
    const isCurrent = () => live && current.current === key;
    setResult((old) => ({ key, viewKey, data: old?.viewKey === viewKey ? old.data : null, error: "", loading: true }));
    const timeout = setTimeout(() => {
      if (!isCurrent()) return;
      live = false;
      controller.abort();
      setResult({ key, viewKey, data: null, loading: false, error: "Расчёт не ответил за 90 секунд. Повторите загрузку." });
    }, 90_000);
    api.tab(shop, tab, query, controller.signal).then((data) => {
      if (!isCurrent()) return;
      if (data.key !== tab) throw new Error("Сервер вернул другую вкладку. Повторите загрузку.");
      setResult({ key, viewKey, data, error: "", loading: false });
    }).catch((error: Error) => {
      if (isCurrent()) setResult({ key, viewKey, data: null, error: error.message || "Не удалось загрузить вкладку.", loading: false });
    }).finally(() => clearTimeout(timeout));
    return () => { live = false; clearTimeout(timeout); controller.abort(); };
  // key includes all query fields; recreating an equivalent query must not restart the request.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, reload]);
  const active = enabled && !!shop;
  const settled = active && result?.key === key;
  return { data: active && result?.viewKey === viewKey ? result.data : null, error: settled ? result.error : "",
    loading: active && (!settled || result.loading) };
}
