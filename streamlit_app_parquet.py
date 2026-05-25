from pathlib import Path
import json

import pandas as pd
import plotly.express as px
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
DETECTED_ANOMALY_FILE = BASE_DIR / "detected_anomaly.parquet"
PREAGGREGATED_BUDGET_FILE = BASE_DIR / "preaggregated_budget_details.parquet"
PREAGGREGATED_SCOPED_DIR = BASE_DIR / "preaggregated_budget_details_scoped"


def to_partition_safe(value: object) -> str:
    return str(value).replace("/", "_").replace("\\", "_").strip()


@st.cache_data(show_spinner=False)
def load_detected_anomaly() -> pd.DataFrame:
    if not DETECTED_ANOMALY_FILE.exists():
        raise FileNotFoundError(f"Missing file: {DETECTED_ANOMALY_FILE}")

    df = pd.read_parquet(DETECTED_ANOMALY_FILE)
    df.columns = [col.lower() for col in df.columns]
    return df


@st.cache_data(show_spinner=False)
def load_cleaned_budget_for_year(year: int) -> pd.DataFrame:
    parquet_file = BASE_DIR / f"cleaned_budget_{year}.parquet"
    if not parquet_file.exists():
        raise FileNotFoundError(f"Missing file: {parquet_file}")

    df = pd.read_parquet(parquet_file)
    df.columns = [col.lower() for col in df.columns]
    return df


@st.cache_data(show_spinner=False)
def load_preaggregated_budget_details() -> pd.DataFrame:
    if not PREAGGREGATED_BUDGET_FILE.exists():
        return pd.DataFrame()

    df = pd.read_parquet(PREAGGREGATED_BUDGET_FILE)
    df.columns = [col.lower() for col in df.columns]
    return df


@st.cache_data(show_spinner=False)
def load_scoped_preaggregated_budget(year: int, department_code: str) -> pd.DataFrame:
    safe_department_code = to_partition_safe(department_code)
    scope_dir = (
        PREAGGREGATED_SCOPED_DIR
        / f"fiscal_year={int(year)}"
        / f"department_code={safe_department_code}"
    )
    if not scope_dir.exists():
        return pd.DataFrame()

    df = pd.read_parquet(scope_dir)
    df.columns = [col.lower() for col in df.columns]
    return df


@st.cache_data(show_spinner=False)
def build_preaggregated_budget_details(year: int, department_name: str) -> pd.DataFrame:
    budget_raw = load_cleaned_budget_for_year(year)

    scoped = budget_raw[
        (budget_raw["department_name"] == department_name)
        & (budget_raw["fiscal_year"].astype(int) == int(year))
    ].copy()

    detail_group_cols = [
        "fiscal_year",
        "department_code",
        "department_name",
        "region_code",
        "region_description",
        "uacs_object_code",
        "org_code",
        "org_name",
        "budget_description",
        "funding_source",
        "full_agency_code",
        "agency_name",
    ]

    detailed_budget = (
        scoped.groupby(detail_group_cols + ["budget_type"], dropna=False)[
            "budget_amount"
        ]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )

    detailed_budget["budget_amount_nep"] = detailed_budget.get("NEP", 0)
    detailed_budget["budget_amount_gaa"] = detailed_budget.get("GAA", 0)
    detailed_budget["abs_change"] = (
        detailed_budget["budget_amount_gaa"] - detailed_budget["budget_amount_nep"]
    )
    detailed_budget["pct_change"] = detailed_budget["abs_change"] / detailed_budget[
        "budget_amount_nep"
    ].replace(0, pd.NA)
    detailed_budget["is_inserted_budget"] = detailed_budget["budget_amount_nep"] == 0
    detailed_budget["is_unapproved_budget"] = detailed_budget["budget_amount_gaa"] == 0

    return detailed_budget


@st.cache_data(show_spinner=False)
def get_preaggregated_budget_for_scope(
    year: int, department_name: str, department_code: str
) -> tuple[pd.DataFrame, str]:
    scoped = load_scoped_preaggregated_budget(year, department_code)
    if not scoped.empty:
        return scoped, "scoped"

    precomputed = load_preaggregated_budget_details()
    if not precomputed.empty:
        scoped = precomputed[
            (precomputed["department_name"] == department_name)
            & (precomputed["fiscal_year"].astype(int) == int(year))
        ].copy()
        if not scoped.empty:
            return scoped, "global"

    # Fallback path when pre-aggregated parquet is missing or does not include the scope.
    return build_preaggregated_budget_details(year, department_name), "runtime"


def build_plain_language_summary(
    nep_value: float,
    gaa_value: float,
    inserted_items: int,
    unapproved_items: int,
    largest_gaa_share: float,
) -> str:
    trend = "approved close to the proposal"
    if gaa_value > nep_value:
        trend = "increased during approval"
    elif gaa_value < nep_value:
        trend = "reduced during approval"

    concentration_line = "Funding looks spread across multiple items."
    if largest_gaa_share >= 0.7:
        concentration_line = (
            "Funding appears highly concentrated in one item, which should be checked."
        )
    elif largest_gaa_share >= 0.4:
        concentration_line = (
            "Funding is somewhat concentrated, so it may need closer review."
        )

    review_bits = []
    if inserted_items > 0:
        review_bits.append("newly inserted items")
    if unapproved_items > 0:
        review_bits.append("items not approved from the proposal")

    if review_bits:
        review_line = (
            "This case needs review because it includes "
            + " and ".join(review_bits)
            + "."
        )
    else:
        review_line = "No inserted or unapproved items are visible in this drill-down."

    return f"The budget was {trend}. {concentration_line} {review_line}"


# ----------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------
st.set_page_config(
    page_title="NEP -> GAA Budget Drift Analyzer (Parquet)",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("NEP -> GAA Budget Drift Analyzer")
st.caption(
    "Identify unusual budget adjustments between proposed (NEP) and approved (GAA) budgets"
)

try:
    anomaly_df = load_detected_anomaly()
except Exception as exc:
    st.error(f"Unable to load detected anomalies: {exc}")
    st.stop()

if anomaly_df.empty:
    st.warning("detected_anomaly.parquet is empty.")
    st.stop()

st.sidebar.header("Filters")

available_years = (
    anomaly_df["fiscal_year"]
    .dropna()
    .astype(int)
    .sort_values(ascending=False)
    .unique()
    .tolist()
)

if not available_years:
    st.warning("No fiscal years found in detected_anomaly.parquet")
    st.stop()

# Preserve previous behavior of skipping the latest year in the dropdown when possible.
selectable_years = available_years[1:] if len(available_years) > 1 else available_years

year = st.sidebar.selectbox("Fiscal Year", selectable_years)

department_rank = (
    anomaly_df.groupby(["department_code", "department_name"], dropna=False)
    .agg(
        total_budget_amount_nep=("budget_amount_nep", "sum"),
        total_budget_amount_gaa=("budget_amount_gaa", "sum"),
    )
    .reset_index()
    .sort_values("total_budget_amount_gaa", ascending=False)
)

department_options = [("", "")] + [
    (str(row["department_code"]), str(row["department_name"]))
    for _, row in department_rank.iterrows()
]

selected_department = st.sidebar.radio(
    "Select Department",
    department_options,
    format_func=lambda x: x[1],
)

department_code, org = selected_department

if not org or not department_code:
    st.info("Select a department to start the analysis.")
    st.stop()

filtered = anomaly_df[
    (anomaly_df["department_name"] == org)
    & (anomaly_df["fiscal_year"].astype(int) == int(year))
].copy()

if filtered.empty:
    st.warning("No data found for the selected department and fiscal year.")
    st.stop()

try:
    # Load precomputed details when available, fallback to on-the-fly preaggregation.
    preaggregated_budget, preaggregation_source = get_preaggregated_budget_for_scope(
        int(year), org, department_code
    )
except Exception as exc:
    st.error(f"Unable to pre-aggregate budget data: {exc}")
    st.stop()

if preaggregation_source == "scoped":
    st.caption("Using fast scoped preloaded aggregated data.")
elif preaggregation_source == "global":
    st.caption("Using global preloaded aggregated data.")
else:
    st.caption(
        "Using on-the-fly aggregation. Generate preloaded parquet for faster startup."
    )

kpi_df = (
    filtered[["budget_amount_nep", "budget_amount_gaa"]]
    .sum()
    .rename(index={"budget_amount_nep": "nep", "budget_amount_gaa": "gaa"})
)

st.subheader("Selected department: " + org)
st.subheader("Executive Summary: NEP vs GAA Impact")

col1, col2, col3 = st.columns(3)

nep_total = float(kpi_df["nep"])
gaa_total = float(kpi_df["gaa"])
net_change = gaa_total - nep_total
pct_change = net_change / nep_total if nep_total > 0 else 0.0

col1.metric("Total NEP Budget", f"P{nep_total:,.0f}")
col2.metric("Total GAA Budget", f"P{gaa_total:,.0f}")
col3.metric("Insertions", f"P{net_change:,.0f}", f"{pct_change:.1%}")

region_df = (
    filtered.groupby("region_description", dropna=False)
    .agg(
        budget_amount_nep=("budget_amount_nep", "sum"),
        budget_amount_gaa=("budget_amount_gaa", "sum"),
    )
    .reset_index()
)

# ----------------------------------------------------
# REGIONAL DISTRIBUTION
# ----------------------------------------------------
st.subheader("Regional Allocation Shifts")

exclude_ncr = st.checkbox("Exclude NCR for comparison")

region_df = region_df.sort_values("budget_amount_gaa", ascending=True)
if exclude_ncr:
    region_df = region_df[
        region_df["region_description"] != "National Capital Region (NCR)"
    ]

region_long = region_df.melt(
    id_vars="region_description",
    var_name="Budget Type",
    value_name="Amount",
)

region_long["Budget Type"] = region_long["Budget Type"].replace(
    {
        "budget_amount_nep": "Proposed Budget (NEP)",
        "budget_amount_gaa": "Approved Budget (GAA)",
    }
)

fig_region = px.bar(
    region_long,
    x="Amount",
    y="region_description",
    color="Budget Type",
    orientation="h",
    title="Regional Distribution",
    barmode="group",
    labels={"region_description": "Region", "Amount": "Budget Amount"},
)

st.plotly_chart(fig_region, use_container_width=True)

# ----------------------------------------------------
# BUDGET OBJECT REALLOCATION
# ----------------------------------------------------
st.subheader("Budget Object Reallocation (Top 10 by Change)")

obj_df = (
    filtered.groupby(["uacs_object_code", "uacs_sub_object_name"], dropna=False)
    .agg(
        budget_amount_nep=("budget_amount_nep", "sum"),
        budget_amount_gaa=("budget_amount_gaa", "sum"),
    )
    .reset_index()
    .sort_values("budget_amount_gaa", ascending=False)
    .head(12)
)

obj_df["change"] = obj_df["budget_amount_gaa"] - obj_df["budget_amount_nep"]
obj_df["pct_change"] = obj_df["change"] / obj_df["budget_amount_nep"].replace(0, pd.NA)

obj_df = obj_df.sort_values("change", ascending=False).head(10).reset_index(drop=True)
obj_df = obj_df[["uacs_sub_object_name", "change"]]

obj_long = obj_df.melt(
    id_vars="uacs_sub_object_name",
    var_name="Budget Type",
    value_name="Amount",
)

fig_obj = px.bar(
    obj_long,
    x="uacs_sub_object_name",
    y="Amount",
    color="Budget Type",
    title="Top 10 Budget Objects by Change.",
)
st.plotly_chart(fig_obj, use_container_width=True)

st.subheader("Budgets Requiring Review")
st.text("Click the checkbox at the left for deeper analysis of the specific budget.")

for_review = filtered[filtered["anomaly_score"] >= 2].sort_values(
    ["anomaly_score", "budget_amount_gaa"], ascending=[False, False]
)

for_review["pct_change_display"] = for_review["pct_change"].apply(
    lambda x: "N/A" if pd.isna(x) else f"{x:.1%}"
)
for_review["flags_detected"] = (
    for_review["anomaly_score"]
    .fillna(0)
    .astype(int)
    .apply(lambda x: "[]" if x <= 0 else " ".join(["🟠"] * x))
)

present_df = for_review[
    [
        "uacs_sub_object_name",
        "region_description",
        "budget_amount_nep",
        "budget_amount_gaa",
        "abs_change",
        "pct_change_display",
        "flags_detected",
    ]
].rename(
    columns={
        "uacs_sub_object_name": "Budget Object",
        "region_description": "Region",
        "budget_amount_nep": "Proposed Budget (NEP)",
        "budget_amount_gaa": "Approved Budget (GAA)",
        "abs_change": "Difference",
        "pct_change_display": "Percent difference",
        "flags_detected": "Flags Detected",
    }
)

present_styled = present_df.style.format(
    {
        "Proposed Budget (NEP)": "{:,.0f}",
        "Approved Budget (GAA)": "{:,.0f}",
        "Difference": "{:,.0f}",
        "Percent difference": "{}",
    }
)

event = st.dataframe(
    present_styled,
    on_select="rerun",
    selection_mode="single-row",
)

selected_indices = event.selection.rows

if selected_indices:
    selected_data = for_review.iloc[selected_indices]

    nep = float(selected_data.iloc[0]["budget_amount_nep"])
    gaa = float(selected_data.iloc[0]["budget_amount_gaa"])
    absolute_change = gaa - nep

    if nep != 0:
        percent_change = (gaa - nep) / nep
    else:
        percent_change = None

    region_description = str(selected_data.iloc[0]["region_description"])
    object_name = str(selected_data.iloc[0]["uacs_sub_object_name"])
    object_code = str(selected_data.iloc[0]["uacs_object_code"])

    selected_scope = preaggregated_budget[
        (preaggregated_budget["region_description"] == region_description)
        & (preaggregated_budget["uacs_object_code"].astype(str) == object_code)
    ].copy()

    balance_check = selected_scope[
        selected_scope["budget_amount_nep"] != selected_scope["budget_amount_gaa"]
    ].copy()

    budget_for_review = balance_check.rename(
        columns={
            "budget_description": "number of unique projects",
            "funding_source": "funding sources",
            "agency_name": "number of agency",
            "org_code": "number of organizations",
            "budget_amount_nep": "Proposed Budget (NEP)",
            "budget_amount_gaa": "Approved Budget (GAA)",
            "is_unapproved_budget": "Unapproved Budget Flag",
            "is_inserted_budget": "Inserted Budget Items",
        }
    )

    budget_summary = (
        budget_for_review[
            [
                "number of unique projects",
                "funding sources",
                "number of agency",
                "number of organizations",
            ]
        ]
        .nunique()
        .to_json()
    )

    budget_summary_numbers = (
        budget_for_review[
            [
                "Proposed Budget (NEP)",
                "Approved Budget (GAA)",
                "Inserted Budget Items",
                "Unapproved Budget Flag",
            ]
        ]
        .sum(numeric_only=False)
        .to_json()
    )

    budget_context = f"""
    - Scope is limited to department = '{org}', fiscal year = '{year}',
      one region = '{region_description}', and one budget object = '{object_name}'.
    - Budget summary: {budget_summary}
    - Budget numbers: {budget_summary_numbers}
    """

    with st.spinner("Looking at metrics..."):
        st.subheader("Investigation Summary")

        col1, col2 = st.columns(2)

        col1.markdown(f"""
        - **Budget Object:** {selected_data.iloc[0]["uacs_sub_object_name"]}
        - **Region:** {selected_data.iloc[0]["region_description"]}
        """)

        percent_change_value = 0 if percent_change is None else percent_change

        col2.markdown(f"""
        - **Proposed Budget Amount (NEP):** P{nep:,.0f}
        - **Approved Budget Amount (GAA):** P{gaa:,.0f}
        - **Percent(%) change:** {percent_change_value:.1%}
        - **Value change:** P{absolute_change:,.0f}
        """)

        st.markdown("#### Why this was flagged?")

        budget_summary = json.loads(budget_summary)
        budget_summary_numbers = json.loads(budget_summary_numbers)

        st.markdown(f"""
        - {selected_data.iloc[0]['explanation']}
        """)

        col1, col2 = st.columns(2)

        col1.write(
            f"- **Projects involved:** {budget_summary['number of unique projects']:,}"
        )
        col1.write(
            f"- **Number of Funding Sources:** {budget_summary['funding sources']}"
        )

        col2.write(f"- **Number of Agencies:** {budget_summary['number of agency']}")
        col2.write(
            f"- **Number of Organizations:** {budget_summary['number of organizations']}"
        )

        proposed_sum = float(budget_summary_numbers.get("Proposed Budget (NEP)", 0))
        approved_sum = float(budget_summary_numbers.get("Approved Budget (GAA)", 0))
        inserted_sum = int(budget_summary_numbers.get("Inserted Budget Items", 0))
        unapproved_sum = int(budget_summary_numbers.get("Unapproved Budget Flag", 0))

        largest_gaa_share = 0.0
        if not budget_for_review.empty and approved_sum > 0:
            largest_gaa_share = (
                budget_for_review["Approved Budget (GAA)"].max() / approved_sum
            )

        generated_explanation = build_plain_language_summary(
            nep_value=proposed_sum,
            gaa_value=approved_sum,
            inserted_items=inserted_sum,
            unapproved_items=unapproved_sum,
            largest_gaa_share=largest_gaa_share,
        )

        df_drift = pd.DataFrame(
            [
                {
                    "Proposed Budget (NEP)": proposed_sum,
                    "Approved Budget (GAA)": approved_sum,
                    "Inserted Items": inserted_sum,
                    "Unapproved Items": unapproved_sum,
                }
            ]
        )

        st.write("Uneven values")
        st.dataframe(
            df_drift.style.format(
                {
                    "Proposed Budget (NEP)": "P{:,.0f}",
                    "Approved Budget (GAA)": "P{:,.0f}",
                }
            )
        )
        st.info(f"""
        **Why this matters**
        - {generated_explanation}
        """)

        st.write("Project Details")
        misaligned_budget = balance_check.copy()

        if misaligned_budget.empty:
            st.success(
                "No misaligned budget lines found for the selected department, region, and budget object."
            )
        else:
            misaligned_budget = misaligned_budget.sort_values(
                "budget_amount_gaa", ascending=False
            )

            st.caption(f"Found {len(misaligned_budget):,} misaligned budget line(s).")

            st.dataframe(
                misaligned_budget[
                    [
                        "budget_description",
                        "org_name",
                        "budget_amount_nep",
                        "budget_amount_gaa",
                        "abs_change",
                        "pct_change",
                        "is_inserted_budget",
                        "is_unapproved_budget",
                        "funding_source",
                    ]
                ]
                .rename(
                    columns={
                        "budget_description": "Project",
                        "org_name": "Organization",
                        "funding_source": "Funding Source",
                        "budget_amount_nep": "Proposed Budget (NEP)",
                        "budget_amount_gaa": "Approved Budget (GAA)",
                        "abs_change": "Difference",
                        "pct_change": "Percent difference",
                        "is_inserted_budget": "Inserted Item",
                        "is_unapproved_budget": "Unapproved Item",
                    }
                )
                .style.format(
                    {
                        "Proposed Budget (NEP)": "P{:,.0f}",
                        "Approved Budget (GAA)": "P{:,.0f}",
                        "Difference": "P{:,.0f}",
                        "Percent difference": lambda x: (
                            "N/A" if pd.isna(x) else f"{x:.1%}"
                        ),
                    }
                ),
                use_container_width=True,
            )
