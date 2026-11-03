import { parseUnreadableRows } from "./auditParsers.js";

export type UnreadableRows = { count: number; ids: string[] };

type HeaderReader = { get(name: string): string | null };

export function readUnreadableRows(headers: HeaderReader): UnreadableRows {
  return parseUnreadableRows(headers);
}

function validationMessage(errors: unknown[]): string {
  const messages = errors.flatMap((item) => {
    if (typeof item !== "object" || item === null) return [];
    const error = item as { loc?: unknown[]; msg?: unknown };
    const location = Array.isArray(error.loc) ? error.loc.map(String).filter((part) => part !== "body") : [];
    const message = typeof error.msg === "string" ? error.msg : "Invalid value";
    return [`${location.length ? `${location.join(" → ")}: ` : ""}${message}`];
  });
  return messages.length ? messages.join("; ") : "The request did not pass validation.";
}

export function formatApiError(status: number, body: unknown): string {
  const isValidation = (value: unknown): boolean => {
    if (Array.isArray(value)) return true;
    if (typeof value !== "object" || value === null) return false;
    return isValidation((value as Record<string, unknown>).detail);
  };
  const describe = (value: unknown): string => {
    if (typeof value === "string") return value.trim();
    if (Array.isArray(value)) return validationMessage(value);
    if (typeof value !== "object" || value === null) return "";
    const row = value as Record<string, unknown>;
    const labels = [row.error, row.message, row.msg].filter(
      (part): part is string => typeof part === "string" && Boolean(part.trim()),
    );
    const nested = describe(row.detail);
    return [...new Set([...labels, nested].filter(Boolean))].join(": ");
  };
  const detail = typeof body === "object" && body !== null && "detail" in body
    ? describe((body as { detail?: unknown }).detail)
    : describe(body);
  if (detail) return `${isValidation(body) ? "Validation failed" : "Request failed"} (${status}): ${detail}`;
  return `Request failed (${status}).`;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
  onResponse?: (response: Response) => void,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  onResponse?.(response);
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, formatApiError(response.status, body));
  }
  try {
    return await response.json() as T;
  } catch {
    throw new ApiError(response.status, `The server returned an unreadable response (${response.status}).`);
  }
}
