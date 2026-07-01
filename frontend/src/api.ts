import type {
  AutonomousRun,
  AutonomousRunRef,
  DatasetCandidate,
  EvidenceCard,
  Project,
  ResearchRoute,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData
      ? init.headers
      : { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail || '请求失败')
  }
  return response.json() as Promise<T>
}

interface TaskRef {
  task_id: string
  status: string
  resource_id?: string | null
}

async function runTask(path: string, init: RequestInit = { method: 'POST' }) {
  const task = await request<TaskRef>(path, init)
  if (!['queued', 'started'].includes(task.status)) return task
  for (let attempt = 0; attempt < 240; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 500))
    const current = await request<TaskRef & { error?: { message?: string } }>(
      `/api/v1/tasks/${task.task_id}`,
    )
    if (current.status === 'completed') return current
    if (['failed', 'canceled'].includes(current.status)) {
      throw new Error(current.error?.message || `任务${current.status === 'failed' ? '失败' : '已取消'}`)
    }
  }
  throw new Error('任务执行超时，请在任务记录中重试该节点')
}

export const listProjects = () => request<Project[]>('/api/v1/projects')
export const getProject = (id: string) => request<Project>(`/api/v1/projects/${id}`)
export const createProject = (payload: { title: string; idea_text: string }) =>
  request<Project>('/api/v1/projects', { method: 'POST', body: JSON.stringify(payload) })
export const runIdeaParse = (id: string) =>
  runTask(`/api/v1/projects/${id}/idea-runs`)
export const runEvidence = (id: string, sources: unknown[] = []) =>
  runTask(`/api/v1/projects/${id}/evidence-runs`, {
    method: 'POST',
    body: JSON.stringify({ sources }),
  })
export const listEvidence = (id: string) =>
  request<EvidenceCard[]>(`/api/v1/projects/${id}/evidence`)
export const runGate = (id: string) =>
  runTask(`/api/v1/projects/${id}/gate-runs`)
export const confirmRoute = (id: string, route: ResearchRoute) =>
  request<Project>(`/api/v1/projects/${id}/route-confirmations`, {
    method: 'POST',
    body: JSON.stringify({ route }),
  })
export const runStudyDesign = (id: string) =>
  runTask(`/api/v1/projects/${id}/study-design-runs`)
export const runReport = (id: string) =>
  runTask(`/api/v1/projects/${id}/report-runs`)
export const runReview = (id: string) =>
  runTask(`/api/v1/projects/${id}/review-runs`)

export async function uploadDocument(id: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request(`/api/v1/projects/${id}/documents`, { method: 'POST', body: form })
}

export async function uploadDataset(id: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<{ id: string; quality_report: Record<string, unknown> }>(
    `/api/v1/projects/${id}/datasets`,
    { method: 'POST', body: form },
  )
}

export const runAnalysis = (
  id: string,
  payload: { dataset_id: string; outcome_column?: string; group_column?: string },
) =>
  runTask(`/api/v1/projects/${id}/analysis-runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const reportDownloadUrl = (id: string, mode: 'draft' | 'final') =>
  `/api/v1/projects/${id}/report.docx?mode=${mode}`

export const regenerateReport = (id: string) =>
  runTask(`/api/v1/projects/${id}/report-regenerations`, {
    method: 'POST',
    body: JSON.stringify({ refresh_evidence: true }),
  })

export const startAutonomousResearch = (projectId: string) =>
  request<AutonomousRunRef>(`/api/v1/projects/${projectId}/autonomous-runs`, {
    method: 'POST',
    body: JSON.stringify({}),
  })

export const getAutonomousRun = (runId: string) =>
  request<AutonomousRun>(`/api/v1/autonomous-runs/${runId}`)

export const cancelAutonomousRun = (runId: string) =>
  request<AutonomousRunRef>(`/api/v1/autonomous-runs/${runId}/cancel`, {
    method: 'POST',
  })

export const resumeAutonomousRun = (runId: string) =>
  request<AutonomousRunRef>(`/api/v1/autonomous-runs/${runId}/resume`, {
    method: 'POST',
  })

export const listDatasetCandidates = (runId: string) =>
  request<DatasetCandidate[]>(
    `/api/v1/autonomous-runs/${runId}/dataset-candidates`,
  )
