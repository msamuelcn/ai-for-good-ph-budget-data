import json
import os
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types


class LLMConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeminiConfig:
    model: str
    temperature: float
    api_key: str

    @staticmethod
    def from_env() -> "GeminiConfig":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise LLMConfigurationError(
                "Missing required environment variable: GEMINI_API_KEY"
            )

        return GeminiConfig(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip(),
            temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
            api_key=api_key,
        )


class GeminiService:
    def __init__(self, config: GeminiConfig):
        self.config = config
        self.client = genai.Client(api_key=config.api_key)

    def generate_sql(
        self, question: str, schema_context: str, max_rows: int
    ) -> dict[str, str]:
        prompt = f"""
You are an expert PostgreSQL analyst for Philippine public budget data.
Convert the user question into one safe SQL query.

Rules:
- Use only these tables in schema ai_for_good_budget_drift:
  - detected_anomaly
  - preaggregated_budget_details
- Output only valid JSON with keys: sql, explanation
- Use ONLY read-only SQL (SELECT or WITH).
- No markdown formatting.
- Add a LIMIT clause of {int(max_rows)} or lower.
- Prefer explicit column names over SELECT *.

Schema metadata:
{schema_context}

User question:
{question}
""".strip()

        response = self.client.models.generate_content(
            model=self.config.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=self.config.temperature,
                response_mime_type="application/json",
            ),
        )

        raw_text = (response.text or "").strip()
        data = self._parse_json(raw_text)

        sql_query = str(data.get("sql", "")).strip()
        explanation = str(data.get("explanation", "")).strip()

        if not sql_query:
            raise RuntimeError("Gemini did not return SQL")

        return {"sql": sql_query, "explanation": explanation}

    def summarize_result(
        self,
        question: str,
        sql_query: str,
        rows: list[dict[str, Any]],
    ) -> str:
        preview = rows[:20]
        prompt = f"""
You are a budget analytics assistant.
Use the query result preview to answer the user's question in plain language.
Do not invent facts that are not in the rows.

Output format:
- 3 to 6 concise bullet points
- Include notable values and caveats when needed

Question:
{question}

SQL used:
{sql_query}

Result preview JSON:
{json.dumps(preview, ensure_ascii=True)}
""".strip()

        response = self.client.models.generate_content(
            model=self.config.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
            ),
        )
        return (response.text or "").strip()

    @staticmethod
    def _parse_json(raw_text: str) -> dict[str, Any]:
        if not raw_text:
            return {}

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(f"Unable to parse JSON from Gemini response: {raw_text}")

        snippet = raw_text[start : end + 1]
        return json.loads(snippet)
