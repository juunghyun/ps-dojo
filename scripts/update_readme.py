#!/usr/bin/env python3
"""README.md의 진행표(<!-- progress:start --> ~ <!-- progress:end -->)를
폴더 구조를 스캔해 자동 생성한다. 별도 설정 파일 없음 — 풀이 파일명이 곧 데이터.

규칙:
  <플랫폼>/<문제폴더>/<아이디>.<확장자>
  숨김 파일과 README.md는 풀이로 치지 않는다.
"""
import re
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
START, END = "<!-- progress:start -->", "<!-- progress:end -->"
EXCLUDE_DIRS = {".git", ".github", "scripts", "docs"}


def scan():
    """{platform: {problem_dir_name: {member: [Path, ...]}}} 구조로 수집한다."""
    data = {}
    for platform in sorted(p for p in ROOT.iterdir()
                           if p.is_dir() and not p.name.startswith(".")
                           and p.name not in EXCLUDE_DIRS):
        problems = {}
        for problem in sorted(p for p in platform.iterdir() if p.is_dir()):
            solutions = {}
            for f in sorted(problem.iterdir()):
                if f.is_file() and not f.name.startswith(".") and f.name.lower() != "readme.md":
                    solutions.setdefault(f.stem, []).append(f)
            if solutions:
                problems[problem.name] = solutions
        if problems:
            data[platform.name] = problems
    return data


def rel_link(path: Path) -> str:
    return "/".join(quote(seg) for seg in path.relative_to(ROOT).parts)


def problem_level(problem_dir: Path) -> str:
    """문제 README 제목의 [level 2]/[Gold III]에서 난이도 추출."""
    readme = problem_dir / "README.md"
    if readme.is_file():
        m = re.match(r"^#\s*\[([^\]]+)\]",
                     readme.read_text(encoding="utf-8", errors="ignore").lstrip())
        if m:
            lv = m.group(1).strip()
            return "Lv." + lv[6:].strip() if lv.lower().startswith("level ") else lv
    return "–"


def render(data) -> str:
    if not data:
        return "아직 풀이가 없습니다. 첫 문제를 풀면 자동으로 채워집니다."

    members = sorted({m for problems in data.values()
                      for sols in problems.values() for m in sols})
    total = sum(len(problems) for problems in data.values())
    solved = {m: sum(1 for problems in data.values()
                     for sols in problems.values() if m in sols) for m in members}

    lines = ["**전체 " + str(total) + "문제** · "
             + " · ".join(f"{m} {solved[m]}" for m in members), ""]

    for platform, problems in data.items():
        lines += [f"### {platform} ({len(problems)})", ""]
        lines.append("| 문제 | 레벨 | " + " | ".join(members) + " |")
        lines.append("| --- | --- | " + " | ".join("---" for _ in members) + " |")
        for name, sols in problems.items():
            problem_dir = ROOT / platform / name
            cells = []
            for m in members:
                if m in sols:
                    cells.append(" · ".join(
                        f"[{f.suffix.lstrip('.')}]({rel_link(f)})" for f in sols[m]))
                else:
                    cells.append("–")
            lines.append(f"| [{name}]({rel_link(problem_dir)}) | {problem_level(problem_dir)} | "
                         + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines).rstrip()


def main():
    text = README.read_text(encoding="utf-8")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    new = head + START + "\n" + render(scan()) + "\n" + END + tail
    if new != text:
        README.write_text(new, encoding="utf-8")
        print("README.md updated")
    else:
        print("no changes")


if __name__ == "__main__":
    main()
