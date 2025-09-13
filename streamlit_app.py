import time
import os
import requests
import streamlit as st

# ========== Page ==========
st.set_page_config(page_title="Tony – Streamlit × GitHub AI Bot", page_icon="🤖", layout="centered")
st.title("🤖 Tony — Streamlit × GitHub AI Bot")
st.caption("Ask Tony directly via OpenAI, or relay via GitHub `/ai` comments to your Action-powered bot.")

# ========== Secrets / Config (same pattern as your previous working app) ==========
def _from_secrets(section: str, key: str, default: str = "") -> str:
    try:
        return (st.secrets.get(section, {}) or {}).get(key, default)
    except Exception:
        return default

# OpenAI key from [openai].api_key or env
OPENAI_KEY = (_from_secrets("openai", "api_key") or os.getenv("OPENAI_API_KEY", "")).strip()
# Optional org; avoid attaching by default (can cause quota-mismatch)
OPENAI_ORG = (_from_secrets("openai", "organization") or os.getenv("OPENAI_ORG") or os.getenv("OPENAI_ORGANIZATION") or "").strip()

# Models: primary + fallbacks (matches earlier fix)
OPENAI_MODEL_PRIMARY   = os.getenv("OPENAI_MODEL_PRIMARY",   "gpt-4o-mini").strip()
OPENAI_MODEL_FALLBACK1 = os.getenv("OPENAI_MODEL_FALLBACK1", "gpt-4o-mini-2024-07-18").strip()
OPENAI_MODEL_FALLBACK2 = os.getenv("OPENAI_MODEL_FALLBACK2", "gpt-3.5-turbo").strip()

# GitHub relay secrets (use flat/root keys unless you want to nest)
GITHUB_PAT = st.secrets.get("GITHUB_PAT", None)
GITHUB_OWNER = st.secrets.get("GITHUB_OWNER", None)
GITHUB_REPO = st.secrets.get("GITHUB_REPO", None)
GITHUB_ISSUE_NUMBER = st.secrets.get("GITHUB_ISSUE_NUMBER", None)

# ========== Session guards / cooldowns ==========
if "last_call_ts" not in st.session_state:
    st.session_state.last_call_ts = 0.0
if "last_prompt" not in st.session_state:
    st.session_state.last_prompt = None
if "last_answer" not in st.session_state:
    st.session_state.last_answer = None
if "relay_last_check_ts" not in st.session_state:
    st.session_state.relay_last_check_ts = 0.0
if "relay_last_send_ts" not in st.session_state:
    st.session_state.relay_last_send_ts = 0.0
if "last_comment_id" not in st.session_state:
    st.session_state.last_comment_id = None
if "last_discussion_url" not in st.session_state:
    st.session_state.last_discussion_url = None

DIRECT_COOLDOWN_SEC = 15     # throttle OpenAI calls (prevents 429 & quota burn)
RELAY_SEND_COOLDOWN = 8      # throttle posting to GitHub
RELAY_CHECK_COOLDOWN = 6     # throttle polling GitHub

# ========== OpenAI wrapper (same “working” logic) ==========
def _get_openai_client():
    if not OPENAI_KEY:
        return None, "Missing OpenAI API key. Put it in Streamlit secrets as:\n[openai]\napi_key = \"sk-...\""
    try:
        import openai
        kwargs = {"api_key": OPENAI_KEY}
        # only attach org if you explicitly want it AND not using a project key
        if OPENAI_ORG and not OPENAI_KEY.startswith("sk-proj-"):
            kwargs["organization"] = OPENAI_ORG
        client = openai.OpenAI(**kwargs)
        return client, None
    except Exception as e:
        return None, f"Failed to init OpenAI client: {e}"

def _chat_once(client, model: str, system_prompt: str, user_text: str, max_tokens: int = 350, temperature: float = 0.6):
    return client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )

def call_openai_with_fallback(user_text: str) -> str:
    """
    - Cooldown + caching (same as your previous app)
    - Avoid forced org header (prevents 'insufficient_quota' due to wrong org)
    - Model fallback: primary → fallback1 → fallback2
    """
    txt = (user_text or "").strip()
    if not txt:
        return "Please enter a prompt."

    # Cooldown for duplicate/repeat clicks
    now = time.time()
    if now - st.session_state.last_call_ts < DIRECT_COOLDOWN_SEC and st.session_state.last_prompt == txt:
        if st.session_state.last_answer:
            return st.session_state.last_answer + "  \n_(cached during cooldown)_"

    # Cache: same prompt → reuse last answer
    if st.session_state.last_prompt == txt and st.session_state.last_answer:
        return st.session_state.last_answer + "  \n_(cached)_"

    if not OPENAI_KEY:
        demo = "🧪 Demo reply — no OpenAI key configured.\n\nQuestion:\n" + txt
        st.session_state.last_prompt = txt
        st.session_state.last_answer = demo
        st.session_state.last_call_ts = time.time()
        return demo

    client, err = _get_openai_client()
    if err:
        return f"OpenAI error: {err}"

    system_prompt = (
        "You are Tony, a friendly robot personal assistant. "
        "Be concise, helpful, and speak in simple clear sentences."
    )
    models_try = [m for m in [OPENAI_MODEL_PRIMARY, OPENAI_MODEL_FALLBACK1, OPENAI_MODEL_FALLBACK2] if m]

    last_err = None
    for m in models_try:
        try:
            resp = _chat_once(client, m, system_prompt, txt, max_tokens=300, temperature=0.7)
            ans = (resp.choices[0].message.content or "").strip()
            if m != OPENAI_MODEL_PRIMARY:
                ans = f"(Fallback: {m}) " + ans
            st.session_state.last_prompt = txt
            st.session_state.last_answer = ans
            st.session_state.last_call_ts = time.time()
            return ans
        except Exception as e:
            se = str(e)
            last_err = se
            # Fall back only on quota/rate issues; otherwise break fast
            if ("insufficient_quota" in se) or ("You exceeded your current quota" in se) or ("429" in se):
                continue
            else:
                break

    # All failed
    fail = (
        "OpenAI quota/rate error across all configured models. "
        "Try again later or switch to a key/plan with balance.\n\n"
        f"Details: {last_err}"
    )
    st.session_state.last_prompt = txt
    st.session_state.last_answer = fail
    st.session_state.last_call_ts = time.time()
    return fail

# ========== GitHub helpers (rate-limited) ==========
def post_github_comment(owner: str, repo: str, issue_number: int, body: str):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github+json"},
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
        headers={"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github+json"},
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

# ========== UI ==========
tabs = st.tabs(["Direct (OpenAI)", "GitHub Relay (/ai)"])

# ----- Direct tab -----
with tabs[0]:
    st.subheader("Direct chat via OpenAI")
    prompt = st.text_area("Your message to Tony", placeholder="Ask anything…", height=120, key="direct_prompt")

    if st.button("Ask Tony (Direct)"):
        if not OPENAI_KEY:
            st.error("No OpenAI API key found. Add it in Streamlit Cloud secrets:\n[openai]\napi_key = \"sk-...\"")
        elif not prompt.strip():
            st.warning("Please enter a prompt.")
        else:
            now = time.time()
            if now - st.session_state.last_call_ts < DIRECT_COOLDOWN_SEC and st.session_state.last_prompt == prompt.strip():
                st.warning("⏳ Please wait a few seconds before asking again. Showing cached answer.")
                st.markdown("**Tony:**")
                st.write(st.session_state.last_answer or "")
            else:
                with st.spinner("Tony is thinking…"):
                    answer = call_openai_with_fallback(prompt.strip())
                    st.markdown("**Tony:**")
                    st.write(answer)

# ----- GitHub Relay tab -----
with tabs[1]:
    st.subheader("Relay via GitHub `/ai` comment")
    if not all([GITHUB_PAT, GITHUB_OWNER, GITHUB_REPO, GITHUB_ISSUE_NUMBER]):
        st.info("Add `GITHUB_PAT`, `GITHUB_OWNER`, `GITHUB_REPO`, and `GITHUB_ISSUE_NUMBER` to your Streamlit secrets to use this tab.")

    relay_prompt = st.text_area(
        "Your message (will be posted as `/ai ...` to a GitHub issue)",
        placeholder="e.g., Summarize the linked discussion and propose next steps.",
        height=120,
        key="relay_prompt",
    )

    col1, col2 = st.columns(2)
    with col1:
        send = st.button("Send to GitHub (/ai)")
    with col2:
        check = st.button("Check for reply")

    # Rate-limit sending
    if send:
        if not all([GITHUB_PAT, GITHUB_OWNER, GITHUB_REPO, GITHUB_ISSUE_NUMBER]):
            st.error("Missing GitHub secrets.")
        elif not relay_prompt.strip():
            st.warning("Please enter a prompt.")
        else:
            now = time.time()
            if now - st.session_state.relay_last_send_ts < RELAY_SEND_COOLDOWN:
                st.warning("⏳ Please wait a few seconds before sending another GitHub comment.")
            else:
                try:
                    posted = post_github_comment(GITHUB_OWNER, GITHUB_REPO, int(GITHUB_ISSUE_NUMBER), f"/ai {relay_prompt.strip()}")
                    st.session_state.last_comment_id = posted.get("id")
                    st.session_state.last_discussion_url = posted.get("html_url")
                    st.session_state.relay_last_send_ts = time.time()
                    st.success("Posted to GitHub. Your Action bot will reply in the same thread.")
                    if st.session_state.last_discussion_url:
                        st.markdown(f"[Open thread on GitHub]({st.session_state.last_discussion_url})")
                except Exception as e:
                    st.error(f"Failed to post to GitHub: {e}")

    # Rate-limit polling
    if check:
        if not all([GITHUB_PAT, GITHUB_OWNER, GITHUB_REPO, GITHUB_ISSUE_NUMBER]):
            st.error("Missing GitHub secrets.")
        else:
            now = time.time()
            if now - st.session_state.relay_last_check_ts < RELAY_CHECK_COOLDOWN:
                st.info("Please wait a moment before checking again.")
            else:
                try:
                    comments = list_issue_comments(GITHUB_OWNER, GITHUB_REPO, int(GITHUB_ISSUE_NUMBER))
                    latest_bot = find_latest_bot_reply(comments, st.session_state.last_comment_id)
                    st.session_state.relay_last_check_ts = time.time()
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
st.caption(
    f"OpenAI key: **{'ON' if OPENAI_KEY else 'OFF'}** · "
    f"Org hdr: **{'ON' if OPENAI_ORG and not OPENAI_KEY.startswith('sk-proj-') else 'OFF'}** · "
    f"Model: **{OPENAI_MODEL_PRIMARY}** (fallbacks: {OPENAI_MODEL_FALLBACK1}, {OPENAI_MODEL_FALLBACK2})"
)
