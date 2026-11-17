"""Build a teacher's Android app on GitHub Actions ("Save & build app" in the admin panel).

The workflow .github/workflows/android.yml receives the teacher's config and photo URL, writes them
into the Flutter app and uploads the APK as an artifact named liveteach-<teacher id>-apk.
Needs GITHUB_TOKEN (fine-grained token with Actions: read & write on the repo) and GITHUB_REPO.
"""
import json
import os
import urllib.request

from .share import share_url

API = "https://api.github.com"


class BuildError(RuntimeError):
    pass


def _gh(method: str, path: str, body: dict | None = None):
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPO")
    if not token or not repo:
        raise BuildError("App builds are not connected yet: set GITHUB_TOKEN and GITHUB_REPO on the server")
    req = urllib.request.Request(f"{API}/repos/{repo}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def app_config(teacher: dict) -> dict:
    return {
        "teacherId": teacher["id"],
        "appName": teacher["app_name"] or f"{teacher['name']} AI",
        "teacherName": teacher["name"],
        "subject": teacher["subject"] or "",
        "avatar": "assets/teacher/avatar.jpg",
        "accent": teacher["brand_color"] or "#2DD4BF",
        "shareUrl": share_url(os.environ.get("PUBLIC_BASE_URL", ""), teacher["id"]) if os.environ.get("PUBLIC_BASE_URL") else "",
    }


def trigger_build(teacher: dict, avatar_url: str, api_base_url: str, caller=_gh) -> None:
    caller("POST", "/actions/workflows/android.yml/dispatches", {
        "ref": "main",
        "inputs": {"teacher_id": teacher["id"], "teacher_config": json.dumps(app_config(teacher)),
                   "avatar_url": avatar_url, "api_base_url": api_base_url},
    })


def list_builds(teacher_id: str, caller=_gh) -> list[dict]:
    data = caller("GET", "/actions/workflows/android.yml/runs?event=workflow_dispatch&per_page=50")
    out = []
    for run in data.get("workflow_runs", []):
        if run.get("display_title") != f"APK {teacher_id}":
            continue
        out.append({"id": run["id"], "number": run["run_number"], "status": run["status"],
                    "conclusion": run["conclusion"], "created_at": run["created_at"], "url": run["html_url"]})
    return out
