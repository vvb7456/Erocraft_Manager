import type { ErrorCode } from './errorCodes'

export interface ErrorInfo {
  code: ErrorCode
  detail?: string
  params?: Record<string, string | number | boolean>
}

export interface OperationResult {
  action: string
  phase: 'request' | 'execution' | 'observation' | 'acceptance'
  outcome: 'success' | 'failed'
  target?: Record<string, string | number | number[]>
  facts?: Record<string, string | number | boolean>
  error?: ErrorInfo
  succeeded?: number
  failed?: number
  children?: OperationResult[]
}

export interface ProblemDetails extends ErrorInfo {
  type: string
  title: string
  status: number
  fields?: Array<ErrorInfo & { location: 'body' | 'query' | 'path' | 'header'; path: (string | number)[] }>
  context?: Record<string, unknown>
  operation?: OperationResult
}
