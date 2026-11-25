import ast
import io
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GH_PAT", "") or os.environ.get("GITHUB_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

DAILY_LOG_PATH = "reports/daily_log.md"
GEMINI_DASHBOARD_PATH = "gemini_boss/dashboard.md"
BOSS_STATE_PATH = "gemini_boss/state.json"

PREFERRED_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

ALLOWED_FIX_EXTENSIONS = (".py", ".yml", ".yaml", ".json", ".toml", ".sh")
BLOCKED_PATHS = (
    ".github/workflows/boss_monitor.yml",
    "scripts/boss_ai.py",
    "gemini_boss/dashboard.md",
    "gemini_boss/state.json",
    "reports/daily_log.md",
)

MAX_RERUNS_PER_RUN_ID = 2


def load_state():
    if os.path.exists(BOSS_STATE_PATH):
        try:
            with open(BOSS_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("rerun_counts", {})
                    data.setdefault("last_fixed_run_id", None)
                    return data
        except Exception:
            pass
    return {"rerun_counts": {}, "last_fixed_run_id": None}


def save_state(state):
    os.makedirs(os.path.dirname(BOSS_STATE_PATH), exist_ok=True)
    with open(BOSS_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def gh_request(url, method="GET", payload=None, retries=3):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "gemini-boss-news-watchdog",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    last_exc = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last_exc


def gh_download_bytes(url, timeout=45):
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "gemini-boss-news-watchdog",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def trigger_workflow(workflow_id_or_file, ref="main", fallback_ref="main"):
    if not (REPO and TOKEN and workflow_id_or_file):
        return False, "Workflow trigger ke liye repo/token missing hai."

    candidates = []
    raw_items = (
        list(workflow_id_or_file)
        if isinstance(workflow_id_or_file, (list, tuple))
        else [workflow_id_or_file]
    )
    for item in raw_items:
        if item is not None and str(item).strip():
            s = str(item).strip()
            if s not in candidates:
                candidates.append(s)
            base = os.path.basename(s)
            if base and base not in candidates:
                candidates.append(base)

    branches = []
    for br in (ref, fallback_ref, "main", "master"):
        if br and br not in branches:
            branches.append(br)

    last_exc = None
    for wf_key in candidates:
        for br in branches:
            url = (
                f"https://api.github.com/repos/{REPO}/actions/workflows/"
                f"{wf_key}/dispatches"
            )
            try:
                gh_request(url, method="POST", payload={"ref": br})
                return True, f"Workflow ({wf_key}) ko {br} par auto-rerun trigger kar diya."
            except Exception as exc:
                last_exc = exc
                continue

    return (
        False,
        f"Workflow auto-rerun trigger fail ({last_exc}). Check karein ke workflow mein workflow_dispatch ho aur GH_PAT ko workflow permission mili ho.",
    )


def discover_gemini_models():
    models = list(PREFERRED_MODELS)
    if not GEMINI_KEY:
        return models
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for item in payload.get("models", []):
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" in methods:
                name = item.get("name", "").replace("models/", "").strip()
                if name and name not in models:
                    models.append(name)
    except Exception as exc:
        print(f"Model discovery warning: {exc}")
    return models


def _call_gemini_model(model_name, prompt, use_json_mime=False):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={GEMINI_KEY}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    if use_json_mime:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    candidates = data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "\n".join(p.get("text", "") for p in parts if "text" in p).strip()


def ask_gemini(prompt, response_mime_type="text/plain"):
    if not GEMINI_KEY:
        return "", "GEMINI_API_KEY secret missing hai."

    want_json = response_mime_type == "application/json"
    errors = []
    model_chain = discover_gemini_models()

    for model_name in model_chain:
        for attempt in range(2):
            try:
                text = _call_gemini_model(model_name, prompt, use_json_mime=want_json)
                if text:
                    print(f"Gemini Boss active model: {model_name}")
                    return text, ""
                if want_json:
                    text = _call_gemini_model(model_name, prompt, use_json_mime=False)
                    if text:
                        print(f"Gemini Boss active model (plain): {model_name}")
                        return text, ""
                errors.append(f"{model_name}: empty response")
                break
            except urllib.error.HTTPError as exc:
                errors.append(f"{model_name} [HTTP {exc.code}]")
                if exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(2)
                    continue
                break
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                break

    return "", " | ".join(errors[-4:]) if errors else "Sab Gemini models fail hue."


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


def sanitize_text(text):
    return re.sub(r"[\u200b-\u200f\ufeff]", "", text)


def validate_candidate_content(path, content):
    if not isinstance(content, str) or not content.strip():
        return False, "Empty content"

    cleaned = sanitize_text(content)
    line_count = len(cleaned.splitlines())
    if line_count < 3:
        return False, f"Code too short ({line_count} lines)"

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                old_content = f.read()
            old_lines = len(old_content.splitlines())
            if old_lines >= 40 and line_count < int(old_lines * 0.45):
                return False, f"Truncated output ({line_count} vs {old_lines} lines)"
        except OSError:
            pass

    if path.endswith(".py"):
        try:
            tree = ast.parse(cleaned)
            compile(tree, filename=path, mode="exec")
        except SyntaxError as exc:
            return False, f"Python SyntaxError (line {exc.lineno}): {exc.msg}"
        except Exception as exc:
            return False, f"Python compile error: {exc}"
    elif path.endswith(".json"):
        try:
            json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return False, f"JSON invalid: {exc}"

    return True, cleaned


def extract_json_object(raw_text):
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE
    ).strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(cleaned[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def fetch_failed_steps_and_logs(run_id):
    failed_steps = []
    log_chunks = []

    try:
        jobs = gh_request(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs"
        ).get("jobs", [])
        for job in jobs:
            job_name = job.get("name", "job")
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    failed_steps.append(f"{job_name} -> {step.get('name')}")
    except Exception as exc:
        log_chunks.append(f"Jobs fetch warning: {exc}")

    # Download run logs zip to extract real traceback/error lines
    try:
        zip_bytes = gh_download_bytes(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/logs"
        )
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for member in zf.namelist():
                if not member.lower().endswith(".txt"):
                    continue
                try:
                    raw_log = zf.read(member).decode("utf-8", errors="replace")
                except Exception:
                    continue
                relevant = []
                for line in raw_log.splitlines():
                    low = line.lower()
                    if any(
                        k in low
                        for k in (
                            "error",
                            "traceback",
                            "exception",
                            "syntaxerror",
                            "modulenotfounderror",
                            "importerror",
                            "failed",
                        )
                    ):
                        relevant.append(line)
                if relevant:
                    log_chunks.append(
                        f"--- {member} ---\n" + "\n".join(relevant[-25:])
                    )
    except Exception as exc:
        log_chunks.append(f"Log archive note: {exc}")

    combined = "\n".join(log_chunks)
    return failed_steps, combined[-2500:] if combined else ""


def try_auto_fix(run_info, failed_steps, error_logs=""):
    if not GEMINI_KEY:
        return False, "GEMINI_API_KEY missing."

    candidate_files = list_repo_files()
    file_snippets = []
    for path in candidate_files[:25]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if len(content) <= 18000:
                file_snippets.append(f"=== FILE: {path} ===\n{content}")
        except OSError:
            continue

    context_text = "\n\n".join(file_snippets) if file_snippets else "No source files."
    feedback_note = ""

    for round_num in range(1, 3):
        prompt = (
            "You are a Principal Python & Automation SRE Engineer running Gemini Boss AI for a 24/7 YouTube news channel pipeline.\n"
            "Diagnose the exact failure from the error logs and write clean, syntactically valid, complete, production-ready code fixes.\n"
            f"Attempt round: {round_num}/2\n"
            f"Failed workflow: {run_info.get('name')} (#{run_info.get('run_number')}, path={run_info.get('path')})\n"
            f"Conclusion: {run_info.get('conclusion')}\n"
            f"Failed steps: {', '.join(failed_steps) if failed_steps else 'Unknown'}\n"
            f"Error logs:\n{error_logs if error_logs else 'N/A'}\n"
            f"{feedback_note}\n"
            "Return STRICT JSON only:\n"
            "{\n"
            '  "can_fix": true or false,\n'
            '  "summary": "concise explanation of root cause and fix",\n'
            '  "edits": [{"path": "relative/path.py", "content": "COMPLETE valid file content"}]\n'
            "}\n"
            "Strict engineering rules:\n"
            "1. Output the ENTIRE file content for every edited file; never truncate or use placeholders.\n"
            "2. Every .py edit must pass ast.parse and compile cleanly with zero SyntaxError or stray characters.\n"
            "3. Keep existing features, resilience, and imports intact.\n"
            "4. Never edit boss_ai.py, boss_monitor.yml, dashboard.md, state.json, or daily_log.md.\n\n"
            f"{context_text}"
        )

        raw, err_detail = ask_gemini(prompt, response_mime_type="application/json")
        if not raw:
            return False, f"Gemini se jawab nahi mila ({err_detail})."

        parsed = extract_json_object(raw)
        if not parsed:
            feedback_note = "\nPrevious output was not valid JSON. Return strict JSON only."
            continue

        can_fix = bool(parsed.get("can_fix"))
        summary = str(parsed.get("summary") or "Analysis complete.").strip()
        edits = parsed.get("edits") if isinstance(parsed.get("edits"), list) else []

        if not can_fix or not edits:
            return False, summary

        applied_files = []
        rejected_notes = []
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            target = str(edit.get("path") or "").strip().lstrip("./")
            new_content = edit.get("content")
            if target not in candidate_files or target in BLOCKED_PATHS:
                rejected_notes.append(f"{target} (blocked/untracked)")
                continue
            ok, validated_or_reason = validate_candidate_content(target, new_content)
            if not ok:
                rejected_notes.append(f"{target} -> {validated_or_reason}")
                continue
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(validated_or_reason)
            applied_files.append(target)

        if applied_files:
            extra = (
                f" (Skipped invalid: {', '.join(rejected_notes)})"
                if rejected_notes
                else ""
            )
            return True, f"{summary} [Fixed: {', '.join(applied_files)}]{extra}"

        feedback_note = (
            f"\nPrevious edit failed validation: {'; '.join(rejected_notes)}. "
            "Fix all syntax/completeness issues and return the complete valid file."
        )

    return False, f"Fix validation failed: {'; '.join(rejected_notes) if rejected_notes else 'No valid edit'}"


def write_outputs(now_str, latest, error_occurred, boss_statement):
    os.makedirs(os.path.dirname(DAILY_LOG_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(GEMINI_DASHBOARD_PATH), exist_ok=True)

    run_label = (
        f"{latest.get('name')} (#{latest.get('run_number')}) - {latest.get('conclusion')}"
        if latest
        else "Koi run nahi mila"
    )
    error_line = (
        "Haan, error detect hua — Gemini Boss ne action liya"
        if error_occurred
        else "Sab healthy hai — koi error nahi"
    )

    dashboard_content = (
        "# Gemini Boss Dashboard\n\n"
        f"## Live Status ({now_str})\n"
        "- **Mode:** 24/7 News Pipeline Watchdog + Log-Aware Auto-Fix + Loop-Guarded Auto-Rerun\n"
        f"- **Latest Target Run:** {run_label}\n"
        f"- **Status:** {error_line}\n"
        f"- **Gemini Boss:** {boss_statement}\n"
    )
    with open(GEMINI_DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(dashboard_content)

    daily_entry = (
        f"\n---\n\n"
        f"## Boss AI Check: {now_str}\n"
        f"- **Run:** {run_label}\n"
        f"- **Status:** {error_line}\n"
        f"- **Boss Action / Note:** {boss_statement}\n"
    )
    with open(DAILY_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(daily_entry)


def main():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    state = load_state()
    rerun_counts = state.get("rerun_counts", {})

    latest = None
    error_occurred = False
    boss_statement = "Pipeline healthy hai; sab workflows smooth chal rahe hain."

    if REPO and TOKEN:
        runs = gh_request(
            f"https://api.github.com/repos/{REPO}/actions/runs?per_page=20"
        ).get("workflow_runs", [])

        other_runs = [
            r for r in runs if r.get("path") != ".github/workflows/boss_monitor.yml"
        ]
        latest = other_runs[0] if other_runs else (runs[0] if runs else None)

        if (
            latest
            and latest.get("path") != ".github/workflows/boss_monitor.yml"
            and latest.get("conclusion") not in (None, "success", "skipped", "cancelled")
        ):
            error_occurred = True
            run_id = str(latest.get("id"))
            failed_steps, log_snippet = fetch_failed_steps_and_logs(run_id)
            fixed, details = try_auto_fix(latest, failed_steps, log_snippet)

            if fixed:
                prev_reruns = int(rerun_counts.get(run_id, 0))
                if prev_reruns < MAX_RERUNS_PER_RUN_ID:
                    wf_targets = [
                        latest.get("workflow_id"),
                        latest.get("path"),
                    ]
                    branch = latest.get("head_branch") or "main"
                    rerun_ok, rerun_msg = trigger_workflow(
                        wf_targets, ref=branch, fallback_ref="main"
                    )
                    if rerun_ok:
                        rerun_counts[run_id] = prev_reruns + 1
                        state["rerun_counts"] = rerun_counts
                        state["last_fixed_run_id"] = run_id
                    boss_statement = f"Auto-fix complete: {details}. {rerun_msg}"
                else:
                    boss_statement = (
                        f"Auto-fix applied: {details}. "
                        f"(Loop guard: run #{latest.get('run_number')} already retried {prev_reruns} times)"
                    )
            else:
                boss_statement = f"Fix attempt status: {details}"

    save_state(state)
    write_outputs(now_str, latest, error_occurred, boss_statement)

    subprocess.run(["git", "config", "user.name", "gemini-boss-ai"], check=False)
    subprocess.run(
        ["git", "config", "user.email", "gemini-boss-ai@users.noreply.github.com"],
        check=Fal
