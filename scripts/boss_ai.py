import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone

REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GH_PAT", "") or os.environ.get("GITHUB_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

DAILY_LOG_PATH = "reports/daily_log.md"
GEMINI_DASHBOARD_PATH = "gemini_boss/dashboard.md"

ALLOWED_FIX_EXTENSIONS = (".py", ".yml", ".yaml", ".json", ".toml", ".sh")
BLOCKED_PATHS = (
    ".github/workflows/boss_monitor.yml",
    "scripts/boss_ai.py",
    "gemini_boss/dashboard.md",
    "reports/daily_log.md",
)


def gh_request(url, method="GET", payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "gemini-boss-ai",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def trigger_workflow(workflow_id_or_file, ref="main"):
    if not (REPO and TOKEN and workflow_id_or_file):
        return False, "Workflow trigger ke liye repo/token missing hai."
    url = (
        f"https://api.github.com/repos/{REPO}/actions/workflows/"
        f"{workflow_id_or_file}/dispatches"
    )
    try:
        gh_request(url, method="POST", payload={"ref": ref})
        return True, f"Workflow ({workflow_id_or_file}) ko {ref} par dobara start kar diya."
    except Exception as exc:
        return False, f"Workflow dobara start nahi ho saka: {exc}"


def ask_gemini(prompt, response_mime_type="text/plain"):
    if not GEMINI_KEY:
        return ""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    )
    generation_config = {}
    if response_mime_type == "application/json":
        generation_config["responseMimeType"] = "application/json"

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    if generation_config:
        payload["generationConfig"] = generation_config

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    candidates = data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "\n".join(p.get("text", "") for p in parts if "text" in p).strip()


def list_repo_files():
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=False
    )
    files = [line.strip() for line in tracked.stdout.splitlines() if line.strip()]
    return [
        f
        for f in files
        if f.endswith(ALLOWED_FIX_EXTENSIONS) and f not in BLOCKED_PATHS
    ]


def try_auto_fix(run_info, failed_steps):
    if not GEMINI_KEY:
        return False, "GEMINI_API_KEY missing."

    candidate_files = list_repo_files()
    file_snippets = []
    for path in candidate_files[:15]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if len(content) <= 6000:
                file_snippets.append(f"=== FILE: {path} ===\n{content}")
        except OSError:
            continue

    context_text = "\n\n".join(file_snippets) if file_snippets else "No source files."
    prompt = (
        "You are Gemini Boss AI supervising a GitHub Actions video automation pipeline.\n"
        f"Failed workflow: {run_info.get('name')} (#{run_info.get('run_number')})\n"
        f"Conclusion: {run_info.get('conclusion')}\n"
        f"Failed steps: {', '.join(failed_steps) if failed_steps else 'Unknown'}\n\n"
        "Return STRICT JSON only:\n"
        '{\n'
        '  "can_fix": true or false,\n'
        '  "summary": "short Roman Urdu/English explanation",\n'
        '  "edits": [{"path": "file.py", "content": "full updated content"}]\n'
        '}\n'
        "Rules: Only edit candidate files. Never touch boss_ai.py or boss_monitor.yml.\n\n"
        f"{context_text}"
    )

    raw = ask_gemini(prompt, response_mime_type="application/json")
    if not raw:
        return False, "Gemini se jawab nahi mila."

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return False, f"Analysis: {raw[:400]}"

    can_fix = bool(parsed.get("can_fix"))
    summary = str(parsed.get("summary") or "Analysis complete.").strip()
    edits = parsed.get("edits") if isinstance(parsed.get("edits"), list) else []

    if not can_fix or not edits:
        return False, summary

    applied_files = []
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        target = str(edit.get("path") or "").strip().lstrip("./")
        new_content = edit.get("content")
        if (
            target in candidate_files
            and target not in BLOCKED_PATHS
            and isinstance(new_content, str)
            and new_content.strip()
        ):
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(new_content)
            applied_files.append(target)

    if not applied_files:
        return False, summary

    return True, f"{summary} (Updated: {', '.join(applied_files)})"


def write_outputs(now_str, latest, error_occurred, boss_statement):
    os.makedirs(os.path.dirname(DAILY_LOG_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(GEMINI_DASHBOARD_PATH), exist_ok=True)

    run_label = (
        f"{latest.get('name')} (#{latest.get('run_number')}) - {latest.get('conclusion')}"
        if latest
        else "Koi run nahi mila"
    )
    error_line = (
        "Haan, error aaya tha — Gemini Boss ne fix kiya"
        if error_occurred
        else "Koi error nahi aaya"
    )

    dashboard_content = (
        "# Gemini Boss Dashboard\n\n"
        f"## Aaj Ka Status ({now_str})\n"
        "- **Mode:** 24/7 Watchdog + Auto-Fix + Auto-Rerun\n"
        f"- **Latest Run:** {run_label}\n"
        f"- **Error Aaya?** {error_line}\n"
        f"- **Gemini:** {boss_statement}\n"
    )
    with open(GEMINI_DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(dashboard_content)

    daily_entry = (
        f"\n---\n\n"
        f"## Boss AI Check: {now_str}\n"
        f"- **Run:** {run_label}\n"
        f"- **Error:** {error_line}\n"
        f"- **Boss Fix / Note:** {boss_statement}\n"
    )
    with open(DAILY_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(daily_entry)


def main():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    latest = None
    failed_steps = []
    error_occurred = False
    boss_statement = "Sab normal hai; koi fix zaroori nahi."

    if REPO and TOKEN:
        runs = gh_request(
            f"https://api.github.com/repos/{REPO}/actions/runs?per_page=10"
        ).get("workflow_runs", [])

        other_runs = [
            r for r in runs if r.get("path") != ".github/workflows/boss_monitor.yml"
        ]
        latest = other_runs[0] if other_runs else (runs[0] if runs else None)

        if (
            latest
            and latest.get("path") != ".github/workflows/boss_monitor.yml"
            and latest.get("conclusion") not in (None, "success", "skipped")
        ):
            error_occurred = True
            run_id = latest["id"]
            jobs = gh_request(
                f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs"
            ).get("jobs", [])
            for job in jobs:
                for step in job.get("steps", []):
                    if step.get("conclusion") == "failure":
                        failed_steps.append(f"{job.get('name')} -> {step.get('name')}")

            fixed, details = try_auto_fix(latest, failed_steps)
            if fixed:
                wf_path = latest.get("path") or str(latest.get("workflow_id") or "")
                branch = latest.get("head_branch") or "main"
                rerun_ok, rerun_msg = trigger_workflow(wf_path, ref=branch)
                boss_statement = (
                    f"Is error ko maine fix kiya hai: {details}. {rerun_msg}"
                    if rerun_ok
                    else f"Is error ko maine fix kiya hai: {details} ({rerun_msg})"
                )
            else:
                boss_statement = f"Error aaya hai: {details}"

    write_outputs(now_str, latest, error_occurred, boss_statement)

    subprocess.run(["git", "config", "user.name", "gemini-boss-ai"], check=False)
    subprocess.run(
        ["git", "config", "user.email", "gemini-boss-ai@users.noreply.github.com"],
        check=False,
    )
    subprocess.run(["git", "add", "."], check=False)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", f"chore(gemini-boss): {now_str}"],
            check=False,
        )
        subprocess.run(["git", "push"], check=False)


if __name__ == "__main__":
    main()
            
