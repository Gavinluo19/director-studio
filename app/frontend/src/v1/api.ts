import type { Bootstrap, Project } from "./types.ts";

let csrf = "";
export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  retrySession = true,
): Promise<T> {
  const headers: Record<string, string> = { "x-studio-csrf": csrf };
  if (body && !(body instanceof FormData))
    headers["content-type"] = "application/json";
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      method,
      credentials: "same-origin",
      headers,
      body:
        body instanceof FormData
          ? body
          : body === undefined
            ? undefined
            : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      "本地后台未连接。请启动片场后台，再重新连接。",
      "network",
      0,
    );
  }
  if (!response.ok) {
    let data: any = {};
    try {
      data = await response.json();
    } catch {}
    if (
      retrySession &&
      path !== "/bootstrap" &&
      response.status === 401 &&
      data.code === "session_required"
    ) {
      await bootstrap();
      return api<T>(path, method, body, false);
    }
    throw new ApiError(
      data.message ||
        (typeof data.detail === "string"
          ? data.detail
          : "操作未完成，请检查输入或重试"),
      data.code || "request_failed",
      response.status,
    );
  }
  if (!response.headers.get("content-type")?.includes("application/json"))
    throw new ApiError(
      "本地 API 代理尚未就绪，请重启片场启动程序。",
      "backend_proxy",
      0,
    );
  return response.json();
}
export async function bootstrap() {
  const data = await api<Bootstrap>("/bootstrap");
  csrf = data.csrf;
  return data;
}
export async function command(
  project: Project,
  type: string,
  payload: Record<string, unknown> = {},
) {
  return api<{ project: Project; job_id?: string; warnings?: string[] }>(
    "/projects/" + project.id + "/commands",
    "POST",
    {
      type,
      payload,
      expected_revision: project.revision,
      idempotency_key: crypto.randomUUID(),
    },
  );
}
