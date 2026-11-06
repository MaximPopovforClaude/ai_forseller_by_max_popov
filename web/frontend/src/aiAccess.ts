/** Display the backend's decision; plan names and user IDs grant no AI access. */
export type AiAccess = { ai_route?: string; ai_ready?: boolean; ai_reason?: string | null };

export function describeAiAccess(access: AiAccess) {
  if (access.ai_ready && access.ai_route === "codex_subscription") return {
    ready: true,
    status: "✓ Codex подключён · VIP",
    detail: "Гномик, ИИ-сводки и разборы работают через подписку Codex владельца. Доступны только разрешённые вам магазины; отдельный API-ключ не нужен.",
  };
  if (access.ai_ready && access.ai_route === "service_api") return {
    ready: true, status: "✓ Нейросеть сервиса подключена",
    detail: "Гномик и аналитика работают через API сервиса.",
  };
  if (access.ai_ready && access.ai_route === "workspace_api") return {
    ready: true, status: "✓ Нейросеть кабинета подключена",
    detail: "Гномик и аналитика работают через API кабинета.",
  };
  return {
    ready: false, status: "Нейросеть пока недоступна",
    detail: access.ai_reason || "Доступ к нейросети для этого кабинета пока не подключён.",
  };
}
