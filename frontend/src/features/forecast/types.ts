export type PredictedDirection = "Bearish" | "Neutral" | "Bullish";

export interface ForecastResponse {
  ticker: string;
  model_name: string;
  return_model_version: string;
  direction_model_version: string;
  feature_version: string;
  dataset_version: string;
  horizon_days: number;
  predicted_direction: PredictedDirection;
  expected_return: number | null;
  probabilities: Record<PredictedDirection, number> | null;
  prediction_timestamp: string;
  data_timestamp: string;
  data_source: string;
  training_period_start: string | null;
  training_period_end: string | null;
  evaluation_period_end: string | null;
  disclaimer: string;
}

export interface FeatureContribution {
  feature: string;
  value: number;
  contribution: number;
  direction: "positive" | "negative";
}

export interface ForecastExplanationResponse {
  ticker: string;
  predicted_direction: PredictedDirection;
  model_version: string;
  feature_version: string;
  as_of: string;
  top_direction_factors: FeatureContribution[];
  top_return_factors: FeatureContribution[];
  data_source: string;
  methodology_note: string;
}
