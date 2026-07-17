export type ResearchRoute = 'A' | 'B' | 'C' | 'D'

export interface ResearchScores {
  information_sufficiency: number
  researchability: number
}

export interface QuestionnaireItem {
  id: string
  dimension: string
  text: string
  type: string
}

export interface Questionnaire {
  title?: string
  items?: QuestionnaireItem[]
  variable_item_map?: Record<string, string[]>
  codebook?: Record<string, unknown>
}

export interface StudyDesign {
  route?: ResearchRoute
  questionnaire?: Questionnaire
  hypotheses?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export interface ResearchReport {
  schema_version?: number
  paper_title?: string
  abstract?: string
  keywords?: string[]
  problem_statement?: {
    current_limitation?: string
    knowledge_gap?: string
    research_question?: string
    evidence_ids?: string[]
  }
  rationale?: {
    innovation?: string
    reasoning_chain?: string[]
    evidence_ids?: string[]
  } | string
  technical_details?: Array<{
    purpose: string
    method: string
    stack: string[]
    execution_status: string
    rationale: string
  }>
  datasets?: {
    source?: Array<Record<string, unknown>>
    simulation_input?: Array<Record<string, unknown>>
    target?: Record<string, unknown>
  }
  methods?: Array<Record<string, unknown>> | string
  experiments?: {
    baselines?: Array<Record<string, unknown>>
    metrics?: Array<Record<string, unknown>>
    validation_design?: string
    robustness_checks?: string[]
  }
  results?: {
    kind?: 'observed_empirical' | 'simulation_feasibility' | 'expected_only'
    status?: string
    sample_size?: number | null
    statistical_findings?: Array<Record<string, unknown>>
    feasibility_conclusion?: string
    limitations?: string[]
  } | string
  limitations_ethics?: Record<string, unknown> | string
  references?: Array<Record<string, unknown>>
  title?: string
  problem?: string
  result_kind?: 'observed' | 'expected_only'
  [key: string]: unknown
}

export interface ReviewResult {
  overall?: 'PASS' | 'WARN' | 'BLOCK'
  checks?: Record<string, unknown>
  agent_review?: Record<string, unknown>
  [key: string]: unknown
}

export interface Project {
  id: string
  owner_id: string
  title: string
  idea_text: string
  stage: string
  route: ResearchRoute | null
  suggested_route: ResearchRoute | null
  research_problem: Record<string, unknown>
  scores: Partial<ResearchScores>
  study_design: StudyDesign
  analysis_result: Record<string, unknown>
  report: ResearchReport
  review: ReviewResult
  evidence_count: number
}

export interface EvidenceCard {
  id: string
  title: string
  source_type: string
  source_url: string
  locator: string
  excerpt: string
  claim: string
  content_hash: string
  trust_status: 'PASS' | 'WARN' | 'BLOCK'
  locked: boolean
}

export type AutonomousStatus =
  | 'queued'
  | 'planning'
  | 'searching_literature'
  | 'searching_datasets'
  | 'ranking_sources'
  | 'validating_evidence'
  | 'awaiting_route_confirmation'
  | 'designing_study'
  | 'downloading_dataset'
  | 'analyzing'
  | 'generating_report'
  | 'reviewing'
  | 'awaiting_real_data'
  | 'paused_risk'
  | 'failed'
  | 'canceled'
  | 'completed'

export interface AutonomousRunRef {
  task_id: string | null
  run_id: string
  status: AutonomousStatus
}

export interface AutonomousRun {
  id: string
  project_id: string
  task_id: string | null
  status: AutonomousStatus
  current_node: string
  config: Record<string, unknown>
  pause_reason: Record<string, unknown>
  cancel_requested: boolean
  error: Record<string, unknown>
  current_iteration?: number
  source_count?: number
  fulltext_count?: number
  claim_count?: number
  coverage?: number
  counter_evidence_coverage?: number
  model_usage?: Record<string, number>
  stop_reason?: string
  degraded_sources?: string[]
}

export interface ResearchIteration {
  iteration: number
  queries: string[]
  metrics: Record<string, number>
  gaps: string[]
  stop_reason: string
}

export interface AutonomousResearchState {
  run_id: string
  limits: Record<string, number | string>
  metrics: {
    current_iteration: number
    source_count: number
    fulltext_count: number
    claim_count: number
    coverage: number
    counter_evidence_coverage: number
    model_usage: Record<string, number>
    stop_reason: string
    degraded_sources: string[]
  }
  iterations: ResearchIteration[]
}

export interface EvidenceGraphClaim {
  id: string
  statement: string
  claim_type: string
}

export interface EvidenceGraphItem {
  id: string
  claim_id: string
  stance: 'supports' | 'counter' | 'qualifies'
  confidence: number
  locator: string
  excerpt: string
  document: {
    id: string
    title: string
    url: string
    license_name: string
  }
}

export interface EvidenceGraph {
  claims: EvidenceGraphClaim[]
  evidence: EvidenceGraphItem[]
}

export interface AutonomousEvent {
  run_id: string
  node: string
  message: string
  progress: number
  timestamp?: string
}

export interface DatasetCandidate {
  id: string
  run_id: string
  project_id: string
  source: string
  external_id: string
  title: string
  provenance_url: string
  score: number
  selected: boolean
  candidate_json: {
    variable_coverage?: number
    license_name?: string
    license_status?: string
    variable_mapping?: Record<string, string>
    excluded_reason?: string
    unit?: string
    [key: string]: unknown
  }
}
