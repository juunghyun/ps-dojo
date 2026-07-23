#!/usr/bin/env python3
"""백준허브 개인 아카이브 레포를 스캔해 ps-dojo 컨벤션 구조로 미러링하고 PR을 자동 오픈한다.

동작:
  1. scripts/mirror_config.json 의 각 멤버 아카이브 레포를 shallow clone
  2. 백준허브 구조(<플랫폼>/<난이도>/<번호>. <문제명>/)에서 풀이 파일 수집
  3. 컨벤션 구조(<platform>/<번호>-<문제명>/<아이디>.<확장자>)로 변환
  4. main과 다른 풀이만 문제별 브랜치(mirror/<아이디>/<platform>-<번호>)로
     커밋·푸시 후 PR 오픈. 새 풀이가 BATCH_THRESHOLD개를 넘으면 일괄 PR 하나로.

같은 브랜치의 PR이 이미 열려 있으면 건드리지 않는다(머지 후 다음 주기에 반영).
로컬 실행도 가능: gh 인증 상태에서 python3 scripts/mirror.py
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "scripts" / "mirror_config.json"
BASELINE_PATH = ROOT / "scripts" / "mirror_baseline.json"
PLATFORM_MAP = {
    "백준": "boj",
    "프로그래머스": "programmers",
    "SWEA": "swea",
    "leetCode": "leetcode",
}
PROBLEM_RE = re.compile(r"^(\d+)\.\s*(.+)$")
LINK_RE = re.compile(r"https?://[^\s\)\"']+")
BATCH_THRESHOLD = 5
BOT_NAME = "ps-dojo-mirror[bot]"
BOT_EMAIL = "ps-dojo-mirror@users.noreply.github.com"


def sh(*args, cwd=ROOT, check=True):
    r = subprocess.run(list(args), cwd=str(cwd), capture_output=True)
    if check and r.returncode != 0:
        sys.stderr.write(r.stderr.decode(errors="replace"))
        raise SystemExit(f"command failed: {' '.join(args)}")
    return r


def nfc(s):
    return unicodedata.normalize("NFC", s)


def slug(title):
    s = re.sub(r"[\s/\\:*?\"<>|.]+", "-", nfc(title)).strip("-")
    return s or "untitled"


def scan_archive(archive_root, username):
    """백준허브 아카이브에서 문제 목록을 수집한다."""
    problems = []
    for platform_dir in sorted(p for p in archive_root.iterdir() if p.is_dir()):
        platform = PLATFORM_MAP.get(nfc(platform_dir.name))
        if not platform:
            continue
        for d in sorted(platform_dir.rglob("*")):
            if not d.is_dir():
                continue
            m = PROBLEM_RE.match(nfc(d.name))
            if not m:
                continue
            pid, title = m.group(1), m.group(2).strip()
            files, link = {}, None
            for f in sorted(d.iterdir()):
                if not f.is_file() or f.name.startswith("."):
                    continue
                if f.name.lower() == "readme.md":
                    found = LINK_RE.search(f.read_text(encoding="utf-8", errors="ignore"))
                    link = found.group(0) if found else None
                elif f.suffix:
                    files[f.suffix] = f.read_bytes()
            if files:
                problems.append({
                    "platform": platform, "pid": pid, "title": title,
                    "dir": f"{platform}/{pid}-{slug(title)}",
                    "files": files, "link": link, "username": username,
                })
    return problems


def main_content(path):
    r = sh("git", "show", f"origin/main:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def digest(content):
    return hashlib.sha256(content).hexdigest()


def load_baseline():
    if BASELINE_PATH.exists():
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {}


def save_baseline(baseline, message):
    BASELINE_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    sh("git", "add", str(BASELINE_PATH))
    sh("git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
       "commit", "-m", message)
    sh("git", "pull", "--rebase", "origin", "main", check=False)
    sh("git", "push", "origin", "HEAD:refs/heads/main")


def plan_changes(problem, member_baseline):
    """main과도 baseline과도 달라 커밋이 필요한 (경로, 내용) 목록."""
    changes = []
    for ext, content in sorted(problem["files"].items()):
        target = f"{problem['dir']}/{problem['username']}{ext}"
        if main_content(target) == content:
            continue
        if member_baseline.get(target) == digest(content):
            continue  # 연동 이전 풀이 — 기록만 하고 PR 제외
        changes.append((target, content))
    # 문제 README는 멤버 무관 동일 내용으로 생성 — 양쪽 PR이 같은 파일을 추가해도 충돌 없음
    readme = f"{problem['dir']}/README.md"
    if changes and main_content(readme) is None:
        body = f"# {problem['pid']}. {problem['title']}\n"
        if problem["link"]:
            body += f"\n- 문제 링크: {problem['link']}\n"
        changes.append((readme, body.encode()))
    return changes


def remote_branch_exists(branch):
    return bool(sh("git", "ls-remote", "--heads", "origin", branch, check=False).stdout.strip())


def pr_body(user, archive, problems):
    lines = ["백준허브 아카이브에서 자동 미러링된 풀이입니다.", ""]
    for p in problems:
        link = p["link"] or "(링크 없음)"
        lines.append(f"- **{p['pid']}. {p['title']}** ({p['platform']}) — {link}")
    lines += [
        "", f"원본 아카이브: https://github.com/{archive}", "",
        f"> 🤖 자동 PR — @{user} 님은 접근법·막힌 지점을 코멘트로 남기고, 상대방은 리뷰를 남겨 주세요.",
    ]
    return "\n".join(lines)


def push_pr(branch, changes, title, body):
    base = tempfile.mkdtemp(prefix="psdojo-wt-")
    wt = str(Path(base) / "wt")
    try:
        sh("git", "worktree", "add", "--detach", wt, "origin/main")
        for path, content in changes:
            f = Path(wt) / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(content)
        sh("git", "add", "-A", cwd=wt)
        sh("git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
           "commit", "-m", title, cwd=wt)
        sh("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=wt)
        r = sh("gh", "pr", "create", "--base", "main", "--head", branch,
               "--title", title, "--body", body, check=False, cwd=wt)
        print(("PR 오픈: " if r.returncode == 0 else "브랜치 푸시됨, PR 생성 실패(수동 확인 필요): ") + branch)
    finally:
        sh("git", "worktree", "remove", "--force", wt, check=False)
        shutil.rmtree(base, ignore_errors=True)


def mirror_member(member, baseline):
    user, archive = member["username"], member["archive"]
    tmp = tempfile.mkdtemp(prefix="psdojo-archive-")
    try:
        r = sh("git", "clone", "--depth", "1", f"https://github.com/{archive}.git", tmp, check=False)
        if r.returncode != 0:
            print(f"skip {user}: {archive} clone 실패 (레포 없음/비공개?)")
            return
        problems = scan_archive(Path(tmp), user)
        if user not in baseline:
            # 첫 스캔 — 연동 시점의 기존 풀이는 baseline으로 기록만 하고 PR을 열지 않는다
            baseline[user] = {
                f"{p['dir']}/{user}{ext}": digest(content)
                for p in problems for ext, content in p["files"].items()
            }
            save_baseline(baseline, f"chore: {user} baseline 등록 ({len(problems)}문제는 연동 이전 풀이로 PR 제외)")
            print(f"{user}: 첫 스캔 — {len(problems)}문제 baseline 기록, PR 없음")
            return
        pending = [(p, plan_changes(p, baseline[user])) for p in problems]
        pending = [(p, c) for p, c in pending if c]
        if not pending:
            print(f"{user}: 새 풀이 없음")
            return
        if len(pending) > BATCH_THRESHOLD:
            branch = f"mirror/{user}/backfill"
            if remote_branch_exists(branch):
                print(f"skip {user}: {branch} PR 대기 중")
                return
            push_pr(branch,
                    [ch for _, cs in pending for ch in cs],
                    f"[mirror] {user} 풀이 {len(pending)}문제 일괄 반영",
                    pr_body(user, archive, [p for p, _ in pending]))
        else:
            for p, changes in pending:
                branch = f"mirror/{user}/{p['platform']}-{p['pid']}"
                if remote_branch_exists(branch):
                    print(f"skip: {branch} PR 대기 중")
                    continue
                push_pr(branch, changes,
                        f"[{p['platform']}] {p['pid']} {p['title']} - {user}",
                        pr_body(user, archive, [p]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sh("git", "fetch", "origin", "main")
    baseline = load_baseline()
    for member in config["members"]:
        mirror_member(member, baseline)


if __name__ == "__main__":
    main()
