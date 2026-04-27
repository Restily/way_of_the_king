/**
 * Fetch wrapper для бэкенда.
 *
 * Подмешивает Authorization Bearer токен из auth store, на 401 пытается
 * рефрешнуть. Если рефреш не удался — выбрасывает ApiError, и auth store
 * уйдёт в unauthenticated.
 */

export class ApiError extends Error {
  public readonly status: number;
  public readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

interface ClientHooks {
  getAccessToken: () => string | null;
  onUnauthorized: () => Promise<void>;
}

let hooks: ClientHooks = {
  getAccessToken: () => null,
  onUnauthorized: async () => {},
};

export function configureClient(next: ClientHooks): void {
  hooks = next;
}

export interface FetchOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  /** false = пропустить Authorization header (для login/refresh). */
  auth?: boolean;
  /** false = не пытаться refresh на 401. */
  retryOnUnauthorized?: boolean;
}

export async function apiFetch<T>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  const {
    auth = true,
    retryOnUnauthorized = true,
    body,
    headers,
    ...rest
  } = options;

  const finalHeaders: Record<string, string> = {
    ...(headers as Record<string, string> | undefined),
  };
  if (body !== undefined && !finalHeaders['Content-Type']) {
    finalHeaders['Content-Type'] = 'application/json';
  }
  if (auth) {
    const token = hooks.getAccessToken();
    if (token) {
      finalHeaders.Authorization = `Bearer ${token}`;
    }
  }

  const response = await fetch(path, {
    ...rest,
    headers: finalHeaders,
    body:
      body === undefined
        ? undefined
        : typeof body === 'string'
          ? body
          : JSON.stringify(body),
  });

  if (response.status === 401 && auth && retryOnUnauthorized) {
    await hooks.onUnauthorized();
    return apiFetch<T>(path, { ...options, retryOnUnauthorized: false });
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const errBody = (await response.json()) as { detail?: string; error?: string };
      detail = errBody.detail ?? errBody.error;
    } catch {
      // body не JSON — игнорируем
    }
    throw new ApiError(response.status, detail ?? 'request_failed');
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }
  return (await response.json()) as T;
}
