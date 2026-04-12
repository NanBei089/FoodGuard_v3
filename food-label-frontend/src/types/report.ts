import type { ReportConversationResponse } from '@/types/report-chat';

export type IngredientRisk = 'safe' | 'warning' | 'danger';

export interface IngredientAnalysisItem {
  name: string;
  risk: IngredientRisk;
  description: string;
  function_category?: string | null;
  rules?: string[];
}

export interface HealthAdviceItem {
  group: string;
  risk: IngredientRisk;
  advice: string;
  hint: string;
}

export interface ReportHazardItem {
  level: string;
  desc: string;
}

export interface ReportNutritionTableRow {
  nutrient_key: string;
  name_cn: string;
  name_en: string | null;
  display_name: string;
  amount: string;
  nrv_percent: number | null;
  nrv_label: string | null;
  recommendation: string;
  level: 'good' | 'neutral' | 'attention' | 'warning';
  is_child: boolean;
  parent_key: string | null;
}

export interface ReportNutritionTable {
  title: string;
  subtitle: string | null;
  serving_basis: string | null;
  parse_source: string | null;
  rows: ReportNutritionTableRow[];
  advice_title: string;
  advice_summary: string | null;
}

export interface ReportAnalysisData {
  score: number;
  summary: string | null;
  hazards: ReportHazardItem[];
  benefits: string[];
  ingredients: IngredientAnalysisItem[];
  health_advice: HealthAdviceItem[];
}

export interface ReportRagSummary {
  total_ingredients: number;
  retrieved_count: number;
  high_match_count: number;
  weak_match_count: number;
  empty_count: number;
}

export interface ReportDetailData {
  report_id: string;
  task_id: string;
  image_url: string;
  ingredients_text: string;
  nutrition: Record<string, string> | null;
  nutrition_table: ReportNutritionTable | null;
  nutrition_parse_source: string | null;
  analysis: ReportAnalysisData;
  rag_summary: ReportRagSummary;
  conversation: ReportConversationResponse | null;
  created_at: string;
}

export type ReportTab = 'ingredients' | 'nutrition' | 'advice';
