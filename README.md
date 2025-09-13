# Streamlit Frontend for GitHub AI Bot

This app gives you two ways to talk to your AI assistant "Tony":
1. **Direct (OpenAI)**: Streamlit calls OpenAI directly with your prompt.
2. **GitHub Relay**: Streamlit posts `/ai ...` to a GitHub Issue. Your GitHub Action bot replies in the thread.

## Secrets
Add these to `.streamlit/secrets.toml` (Streamlit Cloud) or `st.secrets` locally:

```toml
OPENAI_API_KEY = "sk-..."
# For GitHub relay
GITHUB_PAT = "ghp_..."
GITHUB_OWNER = "your-github-user-or-org"
GITHUB_REPO = "your-repo"
GITHUB_ISSUE_NUMBER = 1
```

## Run
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Notes
- The GitHub reply is authored by `github-actions[bot]` when your Action posts back.
- If you changed your Action to post as a different bot/user, adjust the filter in the code.


---
## Streamlit Cloud Deploy Quick Steps
1. Push this folder to a GitHub repo.
2. On Streamlit Cloud, pick the repo/branch and set **App file** = `streamlit_app.py`.
3. Add secrets in **Settings → Secrets** (see `.streamlit/secrets.toml` template).
4. Deploy.
