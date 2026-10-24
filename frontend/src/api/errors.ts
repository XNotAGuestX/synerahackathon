export class ApiError extends Error {
  readonly code: string
  readonly traceId: string
  readonly requestId: string | null
  readonly status: number

  constructor(message: string, code: string, traceId: string, requestId: string | null, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.traceId = traceId
    this.requestId = requestId
    this.status = status
  }
}

export type UiError = {
  message: string
  code: string | null
  traceId: string | null
  requestId: string | null
}

export function toUiError(error: unknown): UiError {
  if (error instanceof ApiError) {
    return { message: error.message, code: error.code, traceId: error.traceId, requestId: error.requestId }
  }
  if (error instanceof Error) return { message: error.message, code: null, traceId: null, requestId: null }
  return { message: 'The request failed.', code: null, traceId: null, requestId: null }
}
