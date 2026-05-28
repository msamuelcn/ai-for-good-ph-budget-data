import streamlit as st

from database import (
    ConfigurationError,
    create_engine,
    fetch_schema_context,
    run_readonly_query,
)
from llm_service import GeminiConfig, GeminiService, LLMConfigurationError

st.set_page_config(
    page_title="Budget Drift Copilot (AlloyDB + Gemini)",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Budget Drift Copilot")
st.caption("Natural language analytics on AlloyDB with Gemini")


@st.cache_resource(show_spinner=False)
def get_engine_cached():
    return create_engine()


@st.cache_resource(show_spinner=False)
def get_llm_cached() -> GeminiService:
    return GeminiService(GeminiConfig.from_env())


@st.cache_data(show_spinner=False)
def get_schema_cached() -> str:
    engine = get_engine_cached()
    return fetch_schema_context(engine)


st.sidebar.header("Runtime Settings")
max_rows = st.sidebar.slider(
    "Max query rows", min_value=50, max_value=2000, value=500, step=50
)
show_sql = st.sidebar.checkbox("Show generated SQL", value=True)

st.sidebar.markdown("Required env vars:")
st.sidebar.code(
    "\n".join(
        [
            "ALLOYDB_INSTANCE_URI",
            "ALLOYDB_DB_USER",
            "ALLOYDB_DB_NAME",
            "ALLOYDB_ENABLE_IAM_AUTH=true|false",
            "ALLOYDB_DB_PASSWORD (if IAM auth is false)",
            "ALLOYDB_IP_TYPE=PUBLIC|PRIVATE",
            "GEMINI_API_KEY",
            "GEMINI_MODEL=gemini-2.0-flash",
        ]
    )
)

try:
    engine = get_engine_cached()
    llm = get_llm_cached()
    schema_context = get_schema_cached()
except (ConfigurationError, LLMConfigurationError) as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:
    st.error(f"Startup failure: {exc}")
    st.stop()

if "history" not in st.session_state:
    st.session_state.history = []

question = st.chat_input(
    "Ask a budget question (example: Top 10 anomalies in 2025 by anomaly_score)"
)

if question:
    with st.spinner("Generating SQL with Gemini..."):
        try:
            generated = llm.generate_sql(
                question=question, schema_context=schema_context, max_rows=max_rows
            )
        except Exception as exc:
            st.error(f"Failed to generate SQL: {exc}")
            st.stop()

    sql_query = generated["sql"]
    generation_note = generated.get("explanation", "")

    if show_sql:
        st.subheader("Generated SQL")
        st.code(sql_query, language="sql")
        if generation_note:
            st.caption(generation_note)

    with st.spinner("Running query on AlloyDB..."):
        try:
            df = run_readonly_query(
                engine=engine, sql_query=sql_query, row_limit=max_rows
            )
        except Exception as exc:
            st.error(f"Query execution failed: {exc}")
            st.stop()

    st.subheader("Query Result")
    st.caption(f"Returned {len(df):,} row(s)")
    st.dataframe(df, use_container_width=True)

    with st.spinner("Synthesizing answer with Gemini..."):
        try:
            answer = llm.summarize_result(
                question=question,
                sql_query=sql_query,
                rows=df.to_dict(orient="records"),
            )
        except Exception as exc:
            answer = f"Unable to synthesize a final narrative: {exc}"

    st.subheader("Answer")
    st.markdown(answer)

    st.session_state.history.insert(
        0,
        {
            "question": question,
            "sql": sql_query,
            "rows": int(len(df)),
        },
    )

if st.session_state.history:
    st.divider()
    st.subheader("Recent Questions")
    for item in st.session_state.history[:8]:
        st.markdown(f"- {item['question']} ({item['rows']} rows)")
        if show_sql:
            st.code(item["sql"], language="sql")
