"""ATS Resume Checker - Streamlit + Google Gemini Flash.

Upload a resume (PDF or DOCX), optionally paste a job description, and get:
  * an overall ATS score (rule-based checks + AI evaluation)
  * a score breakdown
  * strengths, problems, missing keywords and concrete improvements
"""

import io
import json
import os
import re

import streamlit as st
from docx import Document
from google import genai
from google.genai import types
from pypdf import PdfReader

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_CHARS = 15000  # resume text sent to the model (keeps requests fast/cheap)
MIN_CHARS = 200  # below this we assume the file is scanned/empty

SECTION_PATTERNS = {
    "Contact information": r"(@|\+?\d[\d\s\-()]{8,})",
    "Summary / Objective": r"\b(summary|objective|profile|about me)\b",
    "Experience": r"\b(experience|employment|work history|internship)\b",
    "Education": r"\b(education|academic|qualification|degree)\b",
    "Skills": r"\b(skills|technical skills|core competencies|expertise)\b",
}

ACTION_VERBS = {
    "led", "managed", "developed", "designed", "built", "created", "improved",
    "increased", "reduced", "implemented", "analyzed", "analysed", "optimized",
    "optimised", "delivered", "launched", "coordinated", "mentored", "achieved",
    "established", "streamlined", "conducted", "authored", "published",
    "collaborated", "executed", "automated", "engineered", "supervised",
}

# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #
def extract_text(uploaded_file) -> str:
    """Return plain text from an uploaded PDF or DOCX file."""
    name = uploaded_file.name.lower()
    data = uploaded_file.getvalue()

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError("This PDF is password-protected.")
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(pages).strip()

    if name.endswith(".docx"):
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:  # many resumes keep content in tables
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        return "\n".join(parts).strip()

    raise ValueError("Unsupported file type. Please upload a PDF or DOCX.")


# --------------------------------------------------------------------------- #
# Rule-based checks (deterministic, no AI needed)
# --------------------------------------------------------------------------- #
def rule_based_checks(text: str) -> dict:
    """Score structural ATS-friendliness out of 100 and list what was found."""
    lower = text.lower()
    words = re.findall(r"[A-Za-z][A-Za-z\-']+", text)
    word_count = len(words)

    checks = []  # (label, passed, points_earned, points_possible, note)

    # 1. Standard sections (50 points, 10 each)
    for label, pattern in SECTION_PATTERNS.items():
        found = re.search(pattern, lower if label != "Contact information" else text)
        checks.append((label, bool(found), 10 if found else 0, 10,
                       "Found" if found else "Not detected"))

    # 2. Length (15 points)
    if 300 <= word_count <= 1000:
        pts, note = 15, f"{word_count} words (good length)"
    elif 150 <= word_count < 300 or 1000 < word_count <= 1400:
        pts, note = 8, f"{word_count} words (a bit short/long)"
    else:
        pts, note = 0, f"{word_count} words (too short/long)"
    checks.append(("Resume length", pts == 15, pts, 15, note))

    # 3. Email + phone (10 points)
    has_email = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text))
    has_phone = bool(re.search(r"\+?\d[\d\s\-()]{8,}\d", text))
    pts = (5 if has_email else 0) + (5 if has_phone else 0)
    note = f"Email: {'yes' if has_email else 'no'}, Phone: {'yes' if has_phone else 'no'}"
    checks.append(("Email & phone", pts == 10, pts, 10, note))

    # 4. Action verbs (10 points)
    used = {w.lower() for w in words} & ACTION_VERBS
    pts = min(10, len(used) * 2)
    checks.append(("Action verbs", pts >= 8, pts, 10, f"{len(used)} strong verbs found"))

    # 5. Quantified achievements (15 points)
    numbers = re.findall(r"\b\d+(?:\.\d+)?\s?(?:%|percent|x|k|\+)|\$\s?\d+|\b\d{2,}\b", text)
    pts = min(15, len(numbers) * 3)
    checks.append(("Quantified results", pts >= 12, pts, 15, f"{len(numbers)} numeric achievements"))

    earned = sum(c[2] for c in checks)
    possible = sum(c[3] for c in checks)
    return {
        "score": round(100 * earned / possible),
        "checks": checks,
        "word_count": word_count,
    }


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #
PROMPT = """You are an expert ATS (Applicant Tracking System) analyst and career coach.
Evaluate the resume below{jd_clause}.

Return ONLY a JSON object with exactly this structure:
{{
  "ats_score": <integer 0-100>,
  "score_breakdown": {{
    "keywords_relevance": <integer 0-100>,
    "formatting_parseability": <integer 0-100>,
    "content_quality": <integer 0-100>,
    "impact_and_metrics": <integer 0-100>
  }},
  "summary": "<2-3 sentence overall assessment>",
  "strengths": ["..."],
  "weaknesses": ["..."],
  "missing_keywords": ["..."],
  "improvements": [
    {{"priority": "High|Medium|Low", "section": "<resume section>",
      "issue": "<what is wrong>", "fix": "<specific action to take>",
      "example": "<short rewritten example line, or empty string>"}}
  ]
}}

Rules:
- Be realistic and strict; do not inflate scores.
- Base every point on the resume text only. Do not invent facts about the candidate.
- Give 3-6 strengths, 3-6 weaknesses and 5-8 improvements, most important first.
- missing_keywords: important role-relevant terms absent from the resume{jd_keywords_clause}.

{jd_block}RESUME:
\"\"\"
{resume}
\"\"\"
"""


def build_prompt(resume_text: str, job_description: str) -> str:
    if job_description.strip():
        return PROMPT.format(
            jd_clause=" against the job description provided",
            jd_keywords_clause=" that appear in the job description",
            jd_block=f'JOB DESCRIPTION:\n"""\n{job_description.strip()[:6000]}\n"""\n\n',
            resume=resume_text[:MAX_CHARS],
        )
    return PROMPT.format(
        jd_clause=" for general ATS-friendliness and overall quality",
        jd_keywords_clause=" for the most likely target role inferred from the resume",
        jd_block="",
        resume=resume_text[:MAX_CHARS],
    )


def parse_json(raw: str) -> dict:
    """Parse model output into a dict, tolerating code fences / stray text."""
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError("The AI response could not be read. Please try again.")


def clamp(value, default=0) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def analyze_with_gemini(resume_text, job_description, api_key, model) -> dict:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=build_prompt(resume_text, job_description),
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    data = parse_json(response.text)

    # Normalise so the UI never crashes on a missing/odd field.
    breakdown = data.get("score_breakdown") or {}
    return {
        "ats_score": clamp(data.get("ats_score")),
        "score_breakdown": {
            "Keywords & relevance": clamp(breakdown.get("keywords_relevance")),
            "Formatting & parseability": clamp(breakdown.get("formatting_parseability")),
            "Content quality": clamp(breakdown.get("content_quality")),
            "Impact & metrics": clamp(breakdown.get("impact_and_metrics")),
        },
        "summary": str(data.get("summary") or ""),
        "strengths": [str(x) for x in (data.get("strengths") or [])],
        "weaknesses": [str(x) for x in (data.get("weaknesses") or [])],
        "missing_keywords": [str(x) for x in (data.get("missing_keywords") or [])],
        "improvements": [i for i in (data.get("improvements") or []) if isinstance(i, dict)],
    }


def friendly_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "api key" in low or "api_key" in low or "permission" in low or "401" in msg or "403" in msg:
        return "The Gemini API key looks invalid or lacks permission. Please check it."
    if "429" in msg or "quota" in low or "rate" in low:
        return "Gemini rate limit or quota reached. Wait a minute and try again."
    if "404" in msg or "not found" in low:
        return "Model not found. Try another model name in the sidebar."
    return f"Something went wrong while contacting Gemini: {msg}"


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
def score_color(score: int) -> str:
    return "#2e7d32" if score >= 75 else "#f9a825" if score >= 50 else "#c62828"


def get_api_key() -> str:
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:  # no secrets file present
        key = ""
    return key or os.environ.get("GEMINI_API_KEY", "")


def main():
    st.set_page_config(page_title="ATS Resume Checker", page_icon="📄", layout="wide")
    st.title("📄 ATS Resume Checker")
    st.caption("Upload your resume to get an ATS score and specific ways to improve it.")

    with st.sidebar:
        st.header("Settings")
        api_key = get_api_key()
        if api_key:
            st.success("API key loaded from secrets/environment.")
        else:
            api_key = st.text_input("Gemini API key", type="password",
                                    help="Get a free key at https://aistudio.google.com/apikey")
        model = st.text_input("Gemini model", value=DEFAULT_MODEL)
        st.markdown("---")
        st.caption("Your resume is sent to the Gemini API for analysis and is not stored by this app.")

    col_left, col_right = st.columns(2)
    with col_left:
        uploaded = st.file_uploader("Upload resume (PDF or DOCX)", type=["pdf", "docx"])
    with col_right:
        job_description = st.text_area(
            "Job description (optional, for a targeted score)", height=160,
            placeholder="Paste the job posting here to check keyword match…")

    if st.button("Analyze resume", type="primary", disabled=uploaded is None):
        if not api_key:
            st.error("Please enter your Gemini API key in the sidebar.")
            st.stop()

        try:
            with st.spinner("Reading your resume…"):
                text = extract_text(uploaded)
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
            st.stop()

        if len(text) < MIN_CHARS:
            st.error("Very little text could be extracted. The file may be a scanned image. "
                     "ATS systems cannot read those either - export a text-based PDF or DOCX.")
            st.stop()

        rules = rule_based_checks(text)
        try:
            with st.spinner("Analyzing with Gemini…"):
                ai = analyze_with_gemini(text, job_description, api_key, model.strip() or DEFAULT_MODEL)
        except Exception as exc:
            st.error(friendly_error(exc))
            st.stop()

        st.session_state["result"] = {"rules": rules, "ai": ai}

    result = st.session_state.get("result")
    if not result:
        return
    rules, ai = result["rules"], result["ai"]
    final = round(0.6 * ai["ats_score"] + 0.4 * rules["score"])

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.markdown(
        f"<div style='text-align:center'><div style='font-size:15px'>Overall ATS score</div>"
        f"<div style='font-size:56px;font-weight:700;color:{score_color(final)}'>{final}/100</div></div>",
        unsafe_allow_html=True)
    c2.metric("AI evaluation", f"{ai['ats_score']}/100")
    c3.metric("Structure checks", f"{rules['score']}/100")
    st.progress(final / 100)
    if ai["summary"]:
        st.info(ai["summary"])

    tab1, tab2, tab3, tab4 = st.tabs(["Improvements", "Strengths & weaknesses", "Keywords", "Score details"])

    with tab1:
        order = {"high": 0, "medium": 1, "low": 2}
        items = sorted(ai["improvements"], key=lambda i: order.get(str(i.get("priority", "")).lower(), 3))
        if not items:
            st.write("No improvements returned.")
        icons = {"high": "🔴", "medium": "🟠", "low": "🟢"}
        for i in items:
            icon = icons.get(str(i.get("priority", "")).lower(), "⚪")
            with st.expander(f"{icon} {i.get('priority', '')} - {i.get('section', 'General')}", expanded=True):
                st.markdown(f"**Issue:** {i.get('issue', '')}")
                st.markdown(f"**Fix:** {i.get('fix', '')}")
                if i.get("example"):
                    st.markdown(f"**Example:** _{i['example']}_")

    with tab2:
        a, b = st.columns(2)
        with a:
            st.subheader("✅ Strengths")
            for s in ai["strengths"]:
                st.markdown(f"- {s}")
        with b:
            st.subheader("⚠️ Weaknesses")
            for w in ai["weaknesses"]:
                st.markdown(f"- {w}")

    with tab3:
        st.subheader("Missing keywords")
        if ai["missing_keywords"]:
            st.markdown(" ".join(f"`{k}`" for k in ai["missing_keywords"]))
        else:
            st.write("No missing keywords identified.")

    with tab4:
        st.subheader("AI score breakdown")
        for label, val in ai["score_breakdown"].items():
            st.write(f"{label}: **{val}/100**")
            st.progress(val / 100)
        st.subheader("Structure checks")
        for label, passed, earned, possible, note in rules["checks"]:
            st.markdown(f"{'✅' if passed else '❌'} **{label}** ({earned}/{possible}) - {note}")
        st.caption("Overall = 60% AI evaluation + 40% structure checks.")


if __name__ == "__main__":
    main()
