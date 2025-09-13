import time
import requests
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="Tony – Streamlit x GitHub AI Bot", page_icon="🤖", layout="centered")
st.title("🤖 Tony — Streamlit × GitHub AI Bot")
st.caption("Ask Tony directly via OpenAI, or relay via GitHub `/ai` comments to your Action-powered bot.")

# --- Secrets & setup ---
# Expected format in Streamlit Cloud secrets:
# [openai]
# api_key = "sk-..."
OPENAI_API_KEY = st.secrets["openai"]["api_key"]

# GitHub relay secrets (root level)
GITHUB_PAT = st.secrets.get("GITHUB_PAT", None)
GITHUB_OWNER = st.secrets.get("GITHUB_OWNER", None)
GITHUB_REPO = st.secrets.get("GITHUB_REPO", None)
GITHUB_ISSUE_NUMBER = st.secrets.get("GITHUB_ISSUE_NUMBER", None)

# ---------------- OpenAI wrapper ----------------
def call_openai(prompt: str) -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)

    try:
        # First try GPT-4o Mini
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are Tony, a friendly robot personal assistant. Be concise, helpful, and speak in simple clear sentences."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()

    except Exception as e:
        # If quota/rate error, retry with GPT-3.5
        if "insufficient_quota" in str(e) or "429" in str(e):
            try:
                resp = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are Tony, a friendly robot personal assistant. Be concise, helpful, and speak in simple clear sentences."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                )
                return "(Fallback to gpt-3.5-turbo) " + resp.choices[0].message.content.strip()
            except Exception as e2:
                return f"OpenAI quota error on both models: {e2}"
        else:
            return f"OpenAI error: {e}"

# ---------------- GitHub helpers ----------------
def post_github_comment(owner: str, repo: str, issue_number: int, body: str):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {GITHUB_PAT}",
            "Accept": "application/vnd.github+json",
        },
        json={"body": body},
        timeout=30,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"GitHub API error {r.status_code}: {r.text}")
    return r.json()

def list_issue_comments(owner: str, repo: str, issue_number: int, per_page: int = 30):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
    r = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {GITHUB_PAT}",
            "Accept": "application/vnd.github+json",
        },
        params={"per_page": per_page},
        timeout=30,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"GitHub API error {r.status_code}: {r.text}")
    return r.json()

def find_latest_bot_reply(comments, since_comment_id: int | None = None):
    bot_logins = {"github-actions[bot]"}
    latest = None
    for c in comments:
        if since_comment_id is not None and c.get("id", 0) <= since_comment_id:
            continue
        user = (c.get("user") or {}).get("login", "")
        if user in bot_logins:
            latest = c
    return latest

# ---------------- Tabs ----------------
tabs = st.tabs(["Direct (OpenAI)", "GitHub Relay (/ai)"])

# ----- Direct (OpenAI) tab -----
with tabs[0]:
    st.subheader("Direct chat via OpenAI")
    prompt = st.text_area("Your message to Tony", placeholder="Ask anything…", height=120, key="direct_prompt")

    # Track cooldown & cache
    if "last_call_time" not in st.session_state:
        st.session_state.last_call_time = 0
    if "last_prompt" not in st.session_state:
        st.session_state.last_prompt = None
    if "last_answer" not in st.session_state:
        st.session_state.last_answer = None

    if st.button("Ask Tony (Direct)"):
        if not OPENAI_API_KEY:
            st.error("No OpenAI API key found in secrets.")
        elif not prompt.strip():
            st.warning("Please enter a prompt.")
        else:
            now = time.time()
            if now - st.session_state.last_call_time < 15:  # 15s cooldown
                st.warning("⏳ Please wait a few seconds before asking again.")
            else:
                st.session_state.last_call_time = now
                with st.spinner("Tony is thinking…"):
                    try:
                        if st.session_state.last_prompt != prompt.strip():
                            answer = call_openai(prompt.strip())
                            st.session_state.last_prompt = prompt.strip()
                            st.session_state.last_answer = answer
                        else:
                            answer = st.session_state.last_answer
                        st.markdown("**Tony:**")
                        st.write(answer)
                    except Exception as e:
                        st.error(f"OpenAI error: {e}")

# ----- GitHub Relay tab -----
with tabs[1]:
    st.subheader("Relay via GitHub `/ai` comment")
    if not all([GITHUB_PAT, GITHUB_OWNER, GITHUB_REPO, GITHUB_ISSUE_NUMBER]):
        st.info("Add `GITHUB_PAT`, `GITHUB_OWNER`, `GITHUB_REPO`, and `GITHUB_ISSUE_NUMBER` to your secrets to use this tab.")
    relay_prompt = st.text_area("Your message (will be posted as `/ai ...` to a GitHub issue)",
                                placeholder="e.g., Summarize the linked discussion and propose next steps.",
                                height=120, key="relay_prompt")

    col1, col2 = st.columns(2)
    with col1:
        send = st.button("Send to GitHub (/ai)")
    with col2:
        check = st.button("Check for reply")

    if "last_comment_id" not in st.session_state:
        st.session_state.last_comment_id = None
    if "last_discussion_url" not in st.session_state:
        st.session_state.last_discussion_url = None

    if send:
        if not all([GITHUB_PAT, GITHUB_OWNER, GITHUB_REPO, GITHUB_ISSUE_NUMBER]):
            st.error("Missing GitHub secrets.")
        elif not relay_prompt.strip():
            st.warning("Please enter a prompt.")
        else:
            try:
                posted = post_github_comment(GITHUB_OWNER, GITHUB_REPO, int(GITHUB_ISSUE_NUMBER),
                                             f"/ai {relay_prompt.strip()}")
                st.session_state.last_comment_id = posted.get("id")
                st.session_state.last_discussion_url = posted.get("html_url")
                st.success("Posted to GitHub. Your Action bot will reply in the same thread.")
                if st.session_state.last_discussion_url:
                    st.markdown(f"[Open thread on GitHub]({st.session_state.last_discussion_url})")
            except Exception as e:
                st.error(f"Failed to post to GitHub: {e}")

    if check:
        if not all([GITHUB_PAT, GITHUB_OWNER, GITHUB_REPO, GITHUB_ISSUE_NUMBER]):
            st.error("Missing GitHub secrets.")
        else:
            try:
                comments = list_issue_comments(GITHUB_OWNER, GITHUB_REPO, int(GITHUB_ISSUE_NUMBER))
                latest_bot = find_latest_bot_reply(comments, st.session_state.last_comment_id)
                if latest_bot:
                    st.success("Bot replied:")
                    st.markdown(latest_bot.get("body") or "_(empty)_")
                    html_url = latest_bot.get("html_url")
                    if html_url:
                        st.markdown(f"[View on GitHub]({html_url})")
                else:
                    st.info("No new bot reply yet. Try again in a few seconds.")
            except Exception as e:
                st.error(f"Failed to fetch comments: {e}")

st.divider()
st.caption("Tip: Use the GitHub relay if you want an audit trail in issues/PRs. Use direct mode for fastest answers.")
