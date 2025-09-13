# scripts/ai_reply.py
import json
import os
import sys
import requests
from openai import OpenAI

SYSTEM_PROMPT = (
    "You are Tony, a friendly robot personal assistant. "
    "Be concise, helpful, and speak in simple clear sentences."
)

def get_event():
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        print("GITHUB_EVENT_PATH not set or file missing.", file=sys.stderr)
        sys.exit(1)
    with open(event_path, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_command_text(comment_body: str) -> str | None:
    """
    Get the text after the first '/ai ' (space required to avoid false positives).
    Example: '/ai Explain the code' -> 'Explain the code'
    """
    marker = "/ai "
    idx = comment_body.find(marker)
    if idx == -1:
        return None
    return comment_body[idx + len(marker):].strip()

def ai_reply(user_text: str) -> str:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

def post_github_comment(owner: str, repo: str, issue_number: int, body: str):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN missing", file=sys.stderr)
        sys.exit(1)

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"body": body},
        timeout=30,
    )
    if r.status_code >= 300:
        print(f"Failed to post comment: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)

def main():
    event = get_event()

    # event context
    repo_full = os.environ.get("REPO", "")
    if "/" not in repo_full:
        print("Missing REPO env (owner/repo)", file=sys.stderr)
        sys.exit(1)
    owner, repo = repo_full.split("/", 1)

    # Extract the issue number and the comment body
    try:
        issue_number = event["issue"]["number"]
        comment_body = event["comment"]["body"]
        comment_author = event["comment"]["user"]["login"]
    except KeyError as e:
        print(f"Unexpected event payload, missing {e}", file=sys.stderr)
        sys.exit(0)  # soft exit to avoid failing unrelated events

    # Ignore bot loops
    if comment_author.endswith("[bot]"):
        print("Ignoring bot comment.")
        sys.exit(0)

    user_text = extract_command_text(comment_body or "")
    if not user_text:
        print("No '/ai ' command found; exiting.")
        sys.exit(0)

    try:
        answer = ai_reply(user_text)
    except Exception as ex:
        # Fail gracefully and inform the thread
        answer = (
            "Sorry, I couldn’t generate a reply right now. "
            f"Error: `{type(ex).__name__}`. Please try again."
        )

    # Optional: include quoted user prompt for context
    reply_md = (
        f"**Tony (AI):**\n\n{answer}\n\n"
        f"<sub>Asked by @{comment_author} with `/ai`</sub>"
    )

    post_github_comment(owner, repo, issue_number, reply_md)
    print("Reply posted.")

if __name__ == "__main__":
    main()
