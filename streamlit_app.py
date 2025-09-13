import time
import os
import requests
import streamlit as st

st.set_page_config(page_title="Tony – Streamlit × GitHub AI Bot", page_icon="🤖", layout="centered")
st.title("🤖 Tony — Streamlit × GitHub AI Bot")
st.caption("Ask Tony directly via OpenAI, or relay via GitHub `/ai` comments to your Action-powered bot.")

# =========================
# Secrets / Config
# =========================
def _sec(section: str, key: str, default: str = "") -> str:
    try:
        return (st.secrets.get(section, {}) or {}).get(key, default)
    except Exception:
        return default

# OpenAI (primary provider)
OPENAI_KEY = (_sec("openai", "api_key") or os.getenv("OPENAI_API_KEY", "")).strip()
OPENAI_ORG = (_sec("openai", "organization") or os.getenv("OPENAI_ORG") or os.getenv("OPENAI_ORGANIZATION") or "").strip()
OPENAI_MODEL_PRIMARY   = os.getenv("OPENAI_MODEL_PRIMARY",   "gpt-4o-mini").strip()
OPENAI_MODEL_FALLBACK1 = os.getenv("OPENAI_MODEL_FALLBACK1", "gpt-4o-mini-2024-07-18").strip()
OPENAI_MODEL_FALLBACK2 = os.getenv("OPENAI_MODEL_FALLBACK2", "gpt-3.5-turbo").strip()

# Azure OpenAI (optional fallback provider)
AZURE_OAI_KEY        = (_sec("azure_openai", "api_key")        or os.getenv("AZURE_OPENAI_API_KEY", "")).strip()
AZURE_OAI_ENDPOINT   = (_sec("azure_openai", "endpoint")       or os.getenv("AZURE_OPENAI_ENDPOINT", "")).strip()  # e.g. https://my-aoai.openai.azure.com
AZURE_OAI_APIVER     = (_sec("azure_openai", "api_version")    or os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")).strip()
AZURE_OAI_DEPLOYMENT = (_sec("azure_openai", "deployment")     or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")).strip()
AZURE_OAI_DEPLOYMENT_FB = (_sec("azure_openai", "deployment_fallback") or os.getenv("AZURE_OPENAI_DEPLOYMENT_FALLBACK", "")).strip()

# GitHub relay
GITHUB_PAT = st.secrets.get("GITHUB_PAT", None)
GITHUB_OWNER = st.secrets.get("GITHUB_OWNER", None)
GITHUB_REPO = st.secrets.get("GITHUB_REPO", None)
GITHUB_ISSUE_NUMBER = st.secrets.get("GITHUB_ISSUE_NUMBER", None)

# =========================
# Session guards / cooldowns
# =========================
if "last_call_ts" not in st.session_state:
    st.session_state.last_call_ts = 0.0
if "last_prompt" not in st.session_state:
    st.session_state.last_prompt = None
if "last_answer" not in st.session_state:
    st.session_state.last_answer = None
if "last_provider" not in st.session_state:
    st.session_state.last_provider = None

if "relay_last_check_ts" not in st.session_state:
    st.session_state.relay_last_check_ts = 0.0
if "relay_last_send_ts" not in st.session_state:
    st.session_state.relay_last_send_ts = 0.0
if "last_comment_id" not in st.session_state:
    st.session_state.last_comment_id = None
if "last_discussion_url" not in st.session_state:
    st.session_state.last_discussion_url = None

DIRECT_COOLDOWN_SEC = 15
RELAY_SEND_COOLDOWN = 8
RELAY_CHECK_COOLDOWN = 6

# =========================
# Provider helpers
# =========================
def _openai_client():
    if not OPENAI_KEY:
        return None, "Missing OpenAI API key. Put it in Streamlit secrets:\n[openai]\napi_key = \"sk-...\""
    try:
        import openai
        kwargs = {"api_key": OPENAI_KEY}
        # only attach org if explicitly set AND key is not a project key
        if OPENAI_ORG and not OPENAI_KEY.startswith("sk-proj-"):
            kwargs["organization"] = OPENAI_ORG
        return openai.OpenAI(**kwargs), None
    excep
