import type {
  ApiErrorBody,
  AuditEvent,
  ReviewTask,
  StatusResponse,
  Vendor,
  VendorDetail,
  VerificationResponse,
} from "./types";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiRequestError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...options?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiRequestError("The API could not be reached. Start the local Compose stack and try again.", "API_UNREACHABLE", 0);
  }

  if (!response.ok) {
    let body: ApiErrorBody = {};
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // Keep the stable local error below when the API did not return JSON.
    }
    throw new ApiRequestError(
      body.error?.message || `Request failed with status ${response.status}`,
      body.error?.code || "API_REQUEST_FAILED",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; database: string }>("/api/health"),
  listVendors: () => request<{ items: Vendor[] }>("/api/vendors"),
  getVendor: (vendorId: string) => request<VendorDetail>(`/api/vendors/${vendorId}`),
  createVendor: (legalName: string) =>
    request<Vendor>("/api/vendors", { method: "POST", body: JSON.stringify({ legal_name: legalName }) }),
  uploadDocument: (vendorId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("doc_type", "COI");
    return request<import("./types").ComplianceDocument>(`/api/vendors/${vendorId}/documents`, {
      method: "POST",
      body: formData,
    });
  },
  verifyDocument: (documentId: string) =>
    request<VerificationResponse>(`/api/documents/${documentId}/verify`, { method: "POST" }),
  getStatus: (vendorId: string) => request<StatusResponse>(`/api/vendors/${vendorId}/status`),
  getLedger: (vendorId: string) => request<{ items: AuditEvent[] }>(`/api/vendors/${vendorId}/ledger`),
  getReviews: () => request<{ items: ReviewTask[] }>("/api/reviews"),
  updateReview: (reviewId: string, value: unknown, field: string) =>
    request<VerificationResponse>(`/api/reviews/${reviewId}`, {
      method: "PATCH",
      body: JSON.stringify({ value, field }),
    }),
};

export { API_BASE_URL };
