CREATE SCHEMA IF NOT EXISTS ai_for_good_budget_drift;

CREATE TABLE IF NOT EXISTS ai_for_good_budget_drift.detected_anomaly (
    fiscal_year integer NOT NULL,
    department_code text,
    department_name text,
    full_agency_code text,
    agency_name text,
    region_code text,
    region_description text,
    uacs_object_code text,
    uacs_sub_object_name text,
    budget_amount_nep numeric(18,2),
    budget_amount_gaa numeric(18,2),
    unapproved_budget boolean,
    inserted_budget boolean,
    abs_change numeric(18,2),
    pct_change numeric(18,6),
    adjustment_type text,
    anomaly_threshold boolean,
    z_score numeric(18,6),
    anomaly_zscore boolean,
    region_mean numeric(18,6),
    region_std numeric(18,6),
    region_anomaly boolean,
    historical_mean numeric(18,6),
    historical_std numeric(18,6),
    historical_anomaly boolean,
    anomaly_score integer,
    is_anomaly boolean,
    explanation text
);

CREATE TABLE IF NOT EXISTS ai_for_good_budget_drift.preaggregated_budget_details (
    fiscal_year integer NOT NULL,
    department_code text,
    department_name text,
    region_code text,
    region_description text,
    uacs_object_code text,
    org_code text,
    org_name text,
    budget_description text,
    funding_source text,
    full_agency_code text,
    agency_name text,
    budget_amount_nep numeric(18,2),
    budget_amount_gaa numeric(18,2),
    abs_change numeric(18,2),
    pct_change numeric(18,6),
    is_inserted_budget boolean,
    is_unapproved_budget boolean
);

CREATE INDEX IF NOT EXISTS idx_detected_anomaly_year_department_score
    ON ai_for_good_budget_drift.detected_anomaly (fiscal_year, department_name, anomaly_score DESC);

CREATE INDEX IF NOT EXISTS idx_detected_anomaly_department_year
    ON ai_for_good_budget_drift.detected_anomaly (department_code, fiscal_year);

CREATE INDEX IF NOT EXISTS idx_preagg_year_department_region_object
    ON ai_for_good_budget_drift.preaggregated_budget_details (fiscal_year, department_code, region_description, uacs_object_code);

CREATE INDEX IF NOT EXISTS idx_preagg_department_year
    ON ai_for_good_budget_drift.preaggregated_budget_details (department_name, fiscal_year);

ANALYZE ai_for_good_budget_drift.detected_anomaly;
ANALYZE ai_for_good_budget_drift.preaggregated_budget_details;
