export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "autollm" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    let msg = data?.error?.message || data?.detail || `请求失败（${res.status}）`;
    if (Array.isArray(data?.detail)) msg = "输入有误：" + data.detail.map((d: { msg: string }) => d.msg).join("；");
    if (typeof msg !== "string") msg = JSON.stringify(msg);
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  get: <T>(u: string) => request<T>("GET", u),
  post: <T>(u: string, b?: unknown) => request<T>("POST", u, b ?? {}),
  put: <T>(u: string, b?: unknown) => request<T>("PUT", u, b ?? {}),
  patch: <T>(u: string, b?: unknown) => request<T>("PATCH", u, b ?? {}),
  del: <T>(u: string) => request<T>("DELETE", u),
};
