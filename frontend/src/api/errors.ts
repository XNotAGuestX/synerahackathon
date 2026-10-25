export type ErrorDetail = { field?: string; code?: string; message?: string }

export class ApiError extends Error {
  readonly code: string
  readonly traceId: string
  readonly requestId: string | null
  readonly status: number
  readonly details: ErrorDetail[]

  constructor(message: string, code: string, traceId: string, requestId: string | null, status: number, details: ErrorDetail[] = []) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.traceId = traceId
    this.requestId = requestId
    this.status = status
    this.details = details
  }
}

export type UiError = {
  message: string
  code: string | null
  traceId: string | null
  requestId: string | null
  details?: ErrorDetail[]
}

export function toUiError(error: unknown): UiError {
  if (error instanceof ApiError) {
    return { message: error.message, code: error.code, traceId: error.traceId, requestId: error.requestId, details: error.details }
  }
  if (error instanceof Error) return { message: error.message, code: null, traceId: null, requestId: null }
  return { message: 'The request failed.', code: null, traceId: null, requestId: null }
}
