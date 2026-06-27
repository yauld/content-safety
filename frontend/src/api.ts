const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export type Decision = 'approved' | 'rejected' | 'needs_review'
export type ModerationStatus = 'completed' | 'interrupted'
export type DecisionStage = 'workflow' | 'agent' | 'human'

export interface ModerateResponse {
  request_id: string | null
  moderation_id: string
  thread_id: string
  status: ModerationStatus
  decision: Decision
  reason: string
  risk_level: 'low' | 'medium' | 'high'
  decision_stage: DecisionStage
  evidence: string[]
  rule_hits: string[]
  confidence: number | null
  interrupt?: Record<string, unknown> | null
}

export interface ReviewSummary {
  pending_total: number
  pending_max_wait_seconds: number
  pending_agent: number
  completed_today: number
}

export interface DashboardMetricGroup {
  total: number
  approved: number
  rejected: number
  needs_review: number
}

export interface DashboardSummary {
  total_requests: number
  completed_total: number
  interrupted_total: number
  auto_completed_total: number
  human_involved_total: number
  workflow: DashboardMetricGroup
  agent: DashboardMetricGroup
  human: DashboardMetricGroup
  pending_total: number
  pending_max_wait_seconds: number
  completed_today: number
  rule_hits: Record<string, number>
  risk_levels: Record<string, number>
  decision_stages: Record<string, number>
  confidence_buckets: Record<string, number>
  waiting_buckets: Record<string, number>
}

export interface ModerationRecord {
  request_id: string | null
  moderation_id: string
  thread_id: string
  scene: string
  user_id: string | null
  content: string
  status: ModerationStatus
  decision: Decision
  reason: string
  risk_level: 'low' | 'medium' | 'high'
  decision_stage: DecisionStage
  evidence: string[]
  rule_hits: string[]
  confidence: number | null
  created_at: string
  updated_at: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `Request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

export function moderate(content: string): Promise<ModerateResponse> {
  return request<ModerateResponse>('/moderate', {
    method: 'POST',
    body: JSON.stringify({
      request_id: `web-${Date.now()}`,
      scene: 'review-console',
      user_id: 'reviewer-demo',
      content,
    }),
  })
}

export function listPending(): Promise<ModerationRecord[]> {
  return request<ModerationRecord[]>('/reviews/pending')
}

export function reviewSummary(): Promise<ReviewSummary> {
  return request<ReviewSummary>('/reviews/summary')
}

export function dashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>('/dashboard/summary')
}

export function listRecent(limit = 5): Promise<ModerationRecord[]> {
  return request<ModerationRecord[]>(`/reviews/recent?limit=${limit}`)
}

export function resumeModeration(
  threadId: string,
  decision: Decision,
  reason: string,
): Promise<ModerateResponse> {
  return request<ModerateResponse>(`/moderate/${threadId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ decision, reason }),
  })
}
