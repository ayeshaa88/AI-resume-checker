# 📄 ATS Resume Checker

A Streamlit app that scores a resume for Applicant Tracking System (ATS) compatibility and gives specific, prioritized improvements, powered by Google Gemini Flash.

## Features

- Upload a resume as **PDF or DOCX**
- Optional **job description** for a targeted keyword match
- **Overall ATS score** = 60% AI evaluation + 40% rule-based structure checks
- Score breakdown: keywords, formatting, content quality, impact and metrics
- Strengths, weaknesses, missing keywords
- Prioritized improvements (High / Medium / Low) with example rewrites

## Project structure

```
ats-resume-checker/
├── app.py
├── requirements.txt
└── README.md
```

## Run locally

1. **Python 3.9+** is required.
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Get a free Gemini API key at https://aistudio.google.com/apikey
4. Provide the key in one of three ways:
   - Paste it into the sidebar when the app runs, **or**
   - Set an environment variable: `export GEMINI_API_KEY="your_key"` (Windows PowerShell: `$env:GEMINI_API_KEY="your_key"`), **or**
   - Create `.streamlit/secrets.toml` containing:
     ```toml
     GEMINI_API_KEY = "your_key"
     ```
5. Start the app:
   ```bash
   streamlit run app.py
   ```

## Push to GitHub

1. Create a new **empty** repository on https://github.com/new (no README, no .gitignore).
2. Add a `.gitignore` so secrets are never committed:
   ```
   __pycache__/
   venv/
   .env
   .streamlit/secrets.toml
   ```
3. In your project folder run:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: ATS resume checker"
   git branch -M main
   git remote add origin https://github.com/<your-username>/ats-resume-checker.git
   git push -u origin main
   ```
   If GitHub asks for a password, use a **Personal Access Token** (GitHub → Settings → Developer settings → Personal access tokens) instead of your account password.

> ⚠️ Never commit your API key. If you do, revoke it immediately in Google AI Studio and create a new one.

## Deploy on Streamlit Community Cloud (free)

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **Create app** and choose **Deploy a public app from GitHub**.
3. Select your repository, branch `main`, and main file path `app.py`.
4. Open **Advanced settings → Secrets** and paste:
   ```toml
   GEMINI_API_KEY = "your_key"
   ```
5. Click **Deploy**. After a minute or two you get a public URL like `https://your-app.streamlit.app`.

Every `git push` to `main` redeploys the app automatically.

## Configuration

| Setting | Where | Default |
|---|---|---|
| Gemini model | Sidebar field (or `DEFAULT_MODEL` in `app.py`) | `gemini-2.5-flash` |
| API key | Secrets, env var `GEMINI_API_KEY`, or sidebar | none |

If Google retires or renames the model, change the model name in the sidebar or `DEFAULT_MODEL`.

## Limitations

- Scanned or image-only PDFs cannot be read (the same is true for real ATS systems). Use a text-based PDF or DOCX.
- The ATS score is an estimate. Real ATS software varies, so treat it as guidance, not a guarantee.
- The resume text is sent to the Gemini API for analysis. Do not upload documents you are not comfortable sharing with that service.
- Only the first ~15,000 characters of a resume are analyzed.

## Troubleshooting

| Problem | Fix |
|---|---|
| "API key looks invalid" | Re-check the key, and that the Gemini API is enabled for it |
| "Rate limit or quota reached" | Wait a minute, or use a different key/model |
| "Model not found" | Change the model name in the sidebar |
| Very little text extracted | The file is probably scanned; export a text-based PDF/DOCX |
