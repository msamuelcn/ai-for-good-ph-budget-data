import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session
import json
import plotly.express as px
from snowflake.cortex import Complete

session = get_active_session()

# st.session_state["for_review"] = ''


# ----------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------
st.set_page_config(
    page_title="NEP → GAA Budget Drift Analyzer",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("NEP → GAA Budget Drift Analyzer")
st.caption("Identify unusual budget adjustments between proposed (NEP) and approved (GAA) budgets")

st.sidebar.header("Filters")


year = st.sidebar.selectbox(
    "Fiscal Year",
    session.sql("SELECT DISTINCT fiscal_year FROM AI_FOR_GOOD_PH_BUDGET_DATA.PUBLIC.DETECTED_ANOMALY ORDER BY fiscal_year DESC").to_pandas()[1:]["FISCAL_YEAR"]
)

org = st.sidebar.radio(
    "Select Department",
    ['']+session.sql("SELECT DEPARTMENT_CODE,DEPARTMENT_NAME,SUM(BUDGET_AMOUNT_NEP) TOTAL_BUDGET_AMOUNT_NEP ,SUM(BUDGET_AMOUNT_GAA) TOTAL_BUDGET_AMOUNT_GAA FROM AI_FOR_GOOD_PH_BUDGET_DATA.PUBLIC.DETECTED_ANOMALY GROUP BY DEPARTMENT_CODE,DEPARTMENT_NAME ORDER BY TOTAL_BUDGET_AMOUNT_GAA DESC;").to_pandas()["DEPARTMENT_NAME"]
)



kpi_df = session.sql(f"""
SELECT
    SUM(BUDGET_AMOUNT_NEP) AS nep,
    SUM(BUDGET_AMOUNT_GAA) AS gaa
FROM AI_FOR_GOOD_PH_BUDGET_DATA.PUBLIC.DETECTED_ANOMALY
WHERE DEPARTMENT_NAME = '{org}'
AND fiscal_year = {year}
""").to_pandas()

st.subheader('🏛️ Selected department: ' + org)

st.subheader("📌 Executive Summary: NEP vs GAA Impact")

col1, col2, col3 = st.columns(3)

# st.dataframe(kpi_df, use_container_width=True)
net_change = kpi_df['GAA'][0]-kpi_df['NEP'][0]
pct_change = net_change / kpi_df['NEP'][0] if kpi_df['NEP'][0] > 0 else 0

col1.metric("Total NEP Budget", f"₱{kpi_df['NEP'][0]:,.0f}")
col2.metric("Total GAA Budget", f"₱{kpi_df['GAA'][0]:,.0f}")
col3.metric("Insertions", f"₱{net_change:,.0f}", f"{pct_change:.1%}")


region_df = session.sql(f"""
SELECT
    REGION_DESCRIPTION,
    SUM(BUDGET_AMOUNT_NEP) AS BUDGET_AMOUNT_NEP,
    SUM(BUDGET_AMOUNT_GAA) AS BUDGET_AMOUNT_GAA
FROM AI_FOR_GOOD_PH_BUDGET_DATA.PUBLIC.DETECTED_ANOMALY
WHERE DEPARTMENT_NAME = '{org}'
AND fiscal_year = {year}
GROUP BY REGION_DESCRIPTION
""").to_pandas()

# region_df["pct_change"] = (region_df["BUDGET_AMOUNT_GAA"] - region_df["BUDGET_AMOUNT_NEP"]) / region_df["BUDGET_AMOUNT_NEP"]

# fig = px.bar(
#     region_df.sort_values("GAA"),
#     x=['NEP',"GAA"],
#     y="REGION_DESCRIPTION",
#     orientation="h",
#     title="Regional Distribution.",
#     barmode='group',
# )

# ----------------------------------------------------
# REGIONAL DISTRIBUTION
# ----------------------------------------------------
st.subheader("🌍 Regional Allocation Shifts")

exclude_ncr = st.checkbox("Exclude NCR for comparison")

region_df  = region_df.sort_values("BUDGET_AMOUNT_GAA", ascending=True)

if exclude_ncr:
    region_df = region_df[region_df["REGION_DESCRIPTION"] != "National Capital Region (NCR)"]

region_long = region_df.melt(
    id_vars="REGION_DESCRIPTION",
    var_name="Budget Type",
    value_name="Amount"
)

region_long['Budget Type'] = region_long['Budget Type'].replace({
    'BUDGET_AMOUNT_NEP': 'Proposed Budget (NEP)',
    'BUDGET_AMOUNT_GAA': 'Approved Budget (GAA)'
})

fig_region = px.bar(
    region_long,
    x="Amount",
    y="REGION_DESCRIPTION",
    color="Budget Type",
    orientation="h",
    title="Regional Distribution",
    barmode='group',
    labels={
        'REGION_DESCRIPTION': 'Region',
        'Amount': 'Budget Amount'
    }
)

st.plotly_chart(fig_region, use_container_width=True)

# ----------------------------------------------------
# BUDGET OBJECT REALLOCATION
# ----------------------------------------------------
st.subheader("🏗️ Budget Object Reallocation (Top 10 by Change)")


obj_df = session.sql(f"""
SELECT
    UACS_OBJECT_CODE,
    UACS_SUB_OBJECT_NAME,
    SUM(BUDGET_AMOUNT_NEP) AS BUDGET_AMOUNT_NEP,
    SUM(BUDGET_AMOUNT_GAA) AS BUDGET_AMOUNT_GAA
FROM AI_FOR_GOOD_PH_BUDGET_DATA.PUBLIC.DETECTED_ANOMALY
WHERE DEPARTMENT_NAME = '{org}'
AND fiscal_year = {year}
GROUP BY UACS_OBJECT_CODE, UACS_SUB_OBJECT_NAME
ORDER BY BUDGET_AMOUNT_GAA DESC
LIMIT 12
""").to_pandas()

obj_df["CHANGE"] = obj_df["BUDGET_AMOUNT_GAA"] - obj_df["BUDGET_AMOUNT_NEP"]

obj_df["pct_change"] = (obj_df["BUDGET_AMOUNT_GAA"] - obj_df["BUDGET_AMOUNT_NEP"]) / obj_df["BUDGET_AMOUNT_NEP"]

obj_df = obj_df.sort_values("CHANGE", ascending=False).head(10).reset_index()

obj_df = obj_df[['UACS_SUB_OBJECT_NAME','CHANGE']]

obj_long = obj_df.melt(
    id_vars="UACS_SUB_OBJECT_NAME",
    var_name="Budget Type",
    value_name="Amount"
)

# st.dataframe(obj_long)

fig_obj = px.bar(
    obj_long,
    x="UACS_SUB_OBJECT_NAME",
    y="Amount",
    color="Budget Type",
    title="Top 10 Budget Objects by Change."
)
st.plotly_chart(fig_obj, use_container_width=True)


st.subheader("🚨 Budgets Requiring Review")

st.text('Click the checkbox at the left for deeper analysis of the specific budget.')

for_review = session.sql(f"""
SELECT
    UACS_SUB_OBJECT_NAME,
    UACS_OBJECT_CODE,
    REGION_DESCRIPTION,
    BUDGET_AMOUNT_NEP,
    BUDGET_AMOUNT_GAA,
    BUDGET_AMOUNT_GAA - BUDGET_AMOUNT_NEP as ABS_CHANGE,
    COALESCE((BUDGET_AMOUNT_GAA - BUDGET_AMOUNT_NEP) / NULLIF(BUDGET_AMOUNT_NEP, 0), NULL) AS PCT_CHANGE,
    explanation,
    anomaly_score
FROM AI_FOR_GOOD_PH_BUDGET_DATA.PUBLIC.DETECTED_ANOMALY
WHERE DEPARTMENT_NAME = '{org}'
AND fiscal_year = {year}
AND anomaly_score >=2
ORDER BY anomaly_score DESC, BUDGET_AMOUNT_GAA DESC
""").to_pandas()

# for_review.rename(columns={'old_name_A': 'new_name_A'})

for_review['PCT_CHANGE'] = for_review['PCT_CHANGE'].apply(
    lambda x: "N/A" if pd.isna(x) else f"{x:.1%}"
)

for_review['Flags Detected'] = for_review['ANOMALY_SCORE'].apply(lambda x: '🟧' * x)

event = st.dataframe(for_review[[
    'UACS_SUB_OBJECT_NAME',
    'REGION_DESCRIPTION',
    'BUDGET_AMOUNT_NEP',
    'BUDGET_AMOUNT_GAA',
    'ABS_CHANGE',
    'PCT_CHANGE',
    'Flags Detected'
]].rename(columns={'UACS_SUB_OBJECT_NAME': 'Budget Object',
                  'REGION_DESCRIPTION': 'Region',
                   'BUDGET_AMOUNT_NEP': 'Proposed Budget (NEP)',
                   'BUDGET_AMOUNT_GAA': 'Approved Budget (GAA)',
                   'ABS_CHANGE': 'Difference',
                   'PCT_CHANGE': 'Percent difference'
                  }
         
         ).style.format({
        'Proposed Budget (NEP)': "{:,.0f}",
        'Approved Budget (GAA)': "{:,.0f}",
        'Difference': "{:,.0f}",
        'Percent difference': "{}"  # already formatted as percentage string
    })
                     ,
                     on_select="rerun", 
    selection_mode="single-row" )

# 1. Get the list of selected integer indices
selected_indices = event.selection.rows

# 2. Extract values using .iloc
if selected_indices:
    # Use iloc to get the specific row(s) from the original data
    selected_data = for_review.iloc[selected_indices]

    
    nep = selected_data.iloc[0]["BUDGET_AMOUNT_NEP"]
    gaa = selected_data.iloc[0]["BUDGET_AMOUNT_GAA"]
    
    absolute_change = gaa - nep
    
    # Use scalar
    if nep != 0:
        percent_change = (gaa - nep) / nep
    else:
        percent_change = None  # or 1.0, depending on how you want to handle zero NEP

    # Access a specific value (e.g., the first selected product name)
    region_description = selected_data.iloc[0]["REGION_DESCRIPTION"]
    object_name =  selected_data.iloc[0]["UACS_SUB_OBJECT_NAME"]
    object_code =  selected_data.iloc[0]["UACS_OBJECT_CODE"]

    budget_for_review = session.sql(f"""
    WITH filtered_budget as
    (    SELECT
            budget_id,budget_type,fiscal_year,budget_amount,budget_description,funding_code,funding_source,department_code,department_name,abbreviation,agency_code,full_agency_code,agency_name,org_code,org_name,region_code,region_description,prexc_fpap_id,uacs_object_code,uacs_classification,uacs_sub_class,uacs_group,uacs_object_name,uacs_sub_object_name
        FROM AI_FOR_GOOD_PH_BUDGET_DATA.PUBLIC.BUDGET_DATA
        WHERE DEPARTMENT_NAME = '{org}'
        AND fiscal_year = {year}
        AND region_description = '{region_description}'
        AND UACS_OBJECT_CODE = '{object_code}'
        ORDER BY budget_amount DESC
    ), nep_table as (
        SELECT 
        budget_description,
        funding_source,
        full_agency_code,
        agency_name,
        org_code,
        org_name,
        sum(budget_amount) as budget_amount_nep
        FROM filtered_budget WHERE budget_type='NEP' GROUP BY 
        budget_description,
        funding_source,
        full_agency_code,
        agency_name,
        org_code,
        org_name
    ), gaa_table as(
        SELECT 
        budget_description,
        funding_source,
        full_agency_code,
        agency_name,
        org_code,
        org_name,
        sum(budget_amount) as budget_amount_gaa
        FROM filtered_budget WHERE budget_type='GAA' GROUP BY 
        budget_description,
        funding_source,
        full_agency_code,
        agency_name,
        org_code,
        org_name
    ),merged_budget as (
        SELECT 
        COALESCE(n.budget_description, g.budget_description) as budget_description,
        COALESCE(n.funding_source, g.funding_source) as funding_source,
        COALESCE(n.full_agency_code, g.full_agency_code) as full_agency_code,
        COALESCE(n.agency_name, g.agency_name) as agency_name,
        COALESCE(n.org_code, g.org_code) as org_code,
        COALESCE(n.org_name, g.org_name) as org_name,
        n.budget_amount_nep,
        g.budget_amount_gaa,
        CASE WHEN g.budget_amount_gaa IS NULL THEN TRUE ELSE FALSE END as is_unapproved_budget,
        CASE WHEN n.budget_amount_nep IS NULL THEN TRUE ELSE FALSE END as is_inserted_budget
    FROM nep_table n 
    FULL OUTER JOIN gaa_table g 
        ON  n.budget_description = g.budget_description
        AND n.funding_source     = g.funding_source
        AND n.full_agency_code   = g.full_agency_code
        AND n.agency_name        = g.agency_name
        AND n.org_code           = g.org_code
        AND n.org_name           = g.org_name
    ), balance_check as (
        SELECT *
        FROM merged_budget
        WHERE COALESCE(budget_amount_nep, 0) != COALESCE(budget_amount_gaa, 0)
    )SELECT * FROM balance_check
    """).to_pandas()

    budget_for_review = budget_for_review.rename(
        columns={'BUDGET_DESCRIPTION': 'number of unique projects', 
                 'FUNDING_SOURCE': 'funding sources',
                'AGENCY_NAME': 'number of agency',
                 'ORG_CODE': 'number of organizations',
                 'BUDGET_AMOUNT_NEP': 'Proposed Budget (NEP)', 
                 'BUDGET_AMOUNT_GAA': 'Approved Budget (GAA)',
                'IS_UNAPPROVED_BUDGET': 'Unapproved Budget Flag',
                 'IS_INSERTED_BUDGET': 'Inserted Budget Items',
                }
    )


    budget_summary = budget_for_review[['number of unique projects','funding sources','number of agency','number of organizations']].nunique().to_json()
    budget_summary_numbers = budget_for_review[['Proposed Budget (NEP)','Approved Budget (GAA)','Inserted Budget Items','Unapproved Budget Flag']].sum().to_json()
    
    # st.text(budget_summary)
    # st.text(budget_summary_numbers)

    # budget_summary_numbers = budget_summary_numbers.rename(
    #     columns={'BUDGET_AMOUNT_NEP': 'Proposed Budget (NEP)', 
    #              'BUDGET_AMOUNT_GAA': 'Approved Budget (GAA)',
    #             'IS_UNAPPROVED_BUDGET': 'Inserted Budget Items',
    #              'IS_INSERTED_BUDGET': 'Unapproved Budget Flag',
    #             }
    # )

    budget_context = f"""
    - Scope is limited to department = '{org}, fiscal year = '{year}', 
    one region = '{region_description}', and one budget object = '{object_name}'.
    - Budget summary: {budget_summary}
    - Budget numbers: {budget_summary_numbers}
    """

    # st.text(budget_context)

    task = f"""
    In plain language, explain what stands out in this budget.

    Guidance:
    - If the proposed budget is zero and funding appears only in GAA, treat this as a late addition.
    - If an inserted budget is present, do not describe the pattern as fully normal.
    - Concentration in a single project or office should be noted.

    Focus on:
    - what happened during approval
    - how concentrated the funding is
    - whether this needs review and why
    """

    prompt = f"""
    You are reviewing a government budget after filtering by department, fiscal year, region, and budget object.
    
    Reference:
    - NEP (National Expenditure Program): proposed budget
    - GAA (General Appropriations Act): approved budget
    - NEP < GAA: budget increased during approval
    - NEP > GAA: budget reduced during approval
    - NEP ≈ GAA: budget largely approved as proposed
    - Inserted Budget: funding that appears in GAA but was not present in NEP
    - Unapproved Budget: funding proposed in NEP that did not appear in GAA
    
    Context:
    {budget_context}

    Task:
    {task}

    Do not use technical or statistical terms.
    Limit the response to 2–3 sentences.
    """

    result = session.sql(
        """
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
          'snowflake-arctic',
          ?
        )
        """,
        params=[prompt]
    ).collect()
    with st.spinner("Looking at metrics..."):
        # budget_summary
        # budget_summary_numbers
        
        st.subheader("🔍 Investigation Summary")
        # Create two columns
        col1, col2 = st.columns(2)
        
        # Left column
        col1.markdown(f"""
        - **Budget Object:** {selected_data.iloc[0]["UACS_SUB_OBJECT_NAME"]}
        - **Region:** {selected_data.iloc[0]["REGION_DESCRIPTION"]}        
        """)
        percent_change_value = 0 if percent_change is None else percent_change
        # Right column
        col2.markdown(f"""
        - **Proposed Budget Amount (NEP):** ₱{nep:,.0f}
        - **Approved Budget Amount (GAA):** ₱{gaa:,.0f}
        - **Percent(%) change:** {percent_change_value:.1%}
        - **Value change:** ₱{absolute_change:,.0f}
        """)

        st.markdown("#### 🚩 Why this was flagged?")
        # st.write(budget_summary)
        budget_summary = json.loads(budget_summary)
        budget_summary_numbers = json.loads(budget_summary_numbers)
        # st.write(budget_summary_numbers)
        st.markdown(f""" 
        • {selected_data.iloc[0]['EXPLANATION']}  
        """)

        # Create two columns
        col1, col2 = st.columns(2)
        
        # Left column
        col1.write(f"- **Projects involved:** {budget_summary['number of unique projects']:,}")
        col1.write(f"- **Number of Funding Sources:** {budget_summary['funding sources']}")
        
        # Right column
        col2.write(f"- **Number of Agencies:** {budget_summary['number of agency']}")
        col2.write(f"- **Number of Organizations:** {budget_summary['number of organizations']}")

        
        df_drift = pd.DataFrame([{
            "Proposed Budget (NEP)": budget_summary_numbers['Proposed Budget (NEP)'],
            "Approved Budget (GAA)": budget_summary_numbers['Approved Budget (GAA)'],
            "Inserted Items": int(budget_summary_numbers['Inserted Budget Items']),
            "Unapproved Items": int(budget_summary_numbers['Unapproved Budget Flag'])
        }])
        st.write('Uneven values')
        st.dataframe(
            df_drift.style.format({
                "Proposed Budget (NEP)": "₱{:,.0f}",
                "Approved Budget (GAA)": "₱{:,.0f}",
                "Absolute Change": "₱{:,.0f}"
            })
        )
        
        st.info(f"""
        **Why this matters**
        - {result[0][0]}
        """)
        
