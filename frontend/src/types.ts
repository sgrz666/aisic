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
  title?: string
  problem?: string
  rationale?: string
  methods?: string
  results?: string
  limitations_ethics?: string
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
