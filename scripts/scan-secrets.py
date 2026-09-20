#!/usr/bin/env python3
"""
万象 / 通用 · 推送前凭据门禁（repo secret gate）

设计原则（来自 repo-secret-gate 技能的教训）：
  **没有自检的扫描器，其「0 命中」毫无意义。** 所以本脚本内置 --selftest：
  在内存 fixture 里种入各类假凭据，断言全部检出，同时断言「长数字 ID 不被误报成手机号」。
  自检不过 → 结论只能是「扫描器不可信」，而不是「仓库干净」。

用法：
  python3 scan-secrets.py --selftest                 # 先跑这个，必须全绿
  python3 scan-secrets.py <目录>                      # 扫工作区
  python3 scan-secrets.py <目录> --tracked            # 只报 git 已跟踪的（命中即退出码 1，可作 pre-push 钩子）
  python3 scan-secrets.py <目录> --extra-pattern <你的token>

关键区分：命中但被 .gitignore 排除 = 预期状态（不算红线）；
         命中且被 git 跟踪 = 真危险（退出码 1）。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

# ── 检测规则 ──────────────────────────────────────────────
# ⚠️ 陷阱记录：JSON 键名带引号（"storePassword": "v"），键名后紧跟的是**闭合引号**而非冒号，
#    所以键名必须写成 ["']?key["']? 形态；全部键名用命名组，避免反向引用错位。
RULES = [
    ("私钥块",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("凭据赋值",
     re.compile(r"""["']?(?P<key>access[_-]?token|api[_-]?key|apikey|secret[_-]?key|secret|passwd|password|auth[_-]?code|private[_-]?key|client[_-]?secret|storePassword|keyPassword|真值是?|真实值是?|实际值是?|口令|密码|令牌|密钥|凭据)["']?\s*[:=：]\s*["']?(?P<val>[^\s"',;{}]{8,})""",
                re.I)),
    ("Bearer/Basic 令牌",
     re.compile(r"(?:Bearer|Basic)\s+[A-Za-z0-9._\-+/=]{16,}")),
    ("URL 内嵌凭据",
     re.compile(r"https?://[^/\s:@]{1,60}:[^/\s@]{6,}@")),
    ("疑似平台令牌",
     re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bsk-[A-Za-z0-9]{20,}\b")),
    ("本地绝对路径",
     re.compile(r"(?:/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|/private/tmp|/var/folders)")),
    ("邮箱地址",
     re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # 独立成词的手机号；用前后 lookaround 排除长数字 ID（坑：7686461399073243174 里含 13990732431）
    ("手机号",
     re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
]

# 豁免（占位符/文档说明/环境变量引用，不是真凭据）
ALLOW_SUBSTR = [
    "example.com", "example.org", "users.noreply", "noreply.github.com",
    "GITEE_TOKEN", "WEWE_AUTH_CODE", "WEWE_DB_PASS", "${{ secrets.", "${GITEE",
    "你的", "自己设", "勿外泄", "<自动生成", "placeholder", "your_", "xxx",
    "secrets.", "***", "...", "口令要求",
]


def is_allowed(matched_value: str) -> bool:
    v = matched_value.strip().strip("\"'")
    if not v or len(v) < 3:
        return True
    # 纯掩码/重复字符
    if set(v) <= set("*·.#-_x "):
        return True
    if len(set(v)) <= 2:
        return True
    if v.startswith("<") and v.endswith(">"):
        return True
    low = v.lower()
    return any(a.lower() in low for a in ALLOW_SUBSTR)


def scan_text(text: str, extra_patterns=None):
    """返回 [(规则名, 命中片段, 行号)]"""
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        for name, rx in RULES:
            for m in rx.finditer(line):
                frag = m.group("val") if (name == "凭据赋值" and "val" in (m.groupdict() or {})) else m.group(0)
                if name == "凭据赋值" and m.groupdict().get("val"):
                    frag = m.group("val")
                if is_allowed(frag):
                    continue
                findings.append((name, frag.strip(), i))
        for p in (extra_patterns or []):
            if p and p in line:
                findings.append(("自定义敏感串", p[:6] + "…" + p[-4:], i))
    return findings


def selftest() -> bool:
    """在内存里种假凭据，断言全部检出；并断言长数字 ID 不误报。"""
    fixtures = [
        ("JSON 键名带引号的凭据", '{"storePassword": "Abc123Secret9"}', True),
        ("env 形式",              "API_KEY=sk-abcdefghijklmnopqrstuvwx", True),
        ("等号带空格",             "password = 'hunter2xyz'", True),
        ("私钥块",                 "-----BEGIN RSA PRIVATE KEY-----", True),
        ("URL 内嵌凭据",           "https://user:pass123456@real-host.cn/x", True),
        ("本地绝对路径",           "path=/Users/someone/private/info.txt", True),
        ("邮箱",                   "contact me: real.person@somecorp.cn", True),
        ("手机号（独立）",          "电话 13812345678 找我", True),
        ("长数字 ID（不应误报）",   "https://x.com/trending/7686461399073243174/", False),
        ("占位符（不应误报）",      '{"password": "<自动生成，勿外泄>"}', False),
        ("模板占位（不应误报）",    "AUTH_CODE=你的授权码", False),
        ("环境变量引用（不应误报）", "Authorization: ${{ secrets.WEWE_AUTH_CODE }}", False),
        ("忽略规则本身（不应误报）", 'ALLOW_SUBSTR = ["placeholder", "your_"]', False),
        ("Secret 名引用（不应误报）", "同一口令要配到 GitHub Secret: WEWE_DB_PASS", False),
        ("模板里的 Secret 说明（不应误报）", "配到 Secret `WEWE_DB_PASS`，勿外泄", False),
        ("真凭据不被豁免放过（重要）", "PASSWORD=RealSecretValue99", True),
        ("真凭据混在说明旁（重要）", "Secret 名是 X，真值是: MyRealToken12345", True),
        ("中文标签的真凭据（重要）", "登录密码：MyPass12345678", True),
        ("中文冒号的真凭据（重要）", "接口密钥：sk-abcdef1234567890", True),
    ]
    ok = True
    for label, text, should_hit in fixtures:
        hits = scan_text(text)
        got = len(hits) > 0
        mark = "✅" if got == should_hit else "❌"
        if got != should_hit:
            ok = False
        detail = f"命中 {hits[0][0]}:{hits[0][1][:24]}" if hits else "无命中"
        print(f"  {mark} {label:<22} 期望{'检出' if should_hit else '不检出'} → {detail}")
    print(f"\n  自检结论：{'全绿，扫描器结果可采信' if ok else '存在失败项 — 扫描器不可信，不得据此下结论'}")
    return ok


def git_tracked(repo: Path):
    try:
        out = subprocess.run(["git", "-C", str(repo), "ls-files"],
                             capture_output=True, text=True, timeout=30)
        return set(out.stdout.split())
    except Exception:
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default=".")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tracked", action="store_true", help="只报 git 已跟踪文件（命中 → 退出码 1）")
    ap.add_argument("--extra-pattern", action="append", default=[], help="额外敏感串（如你自己的 token）")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    root = Path(args.target).resolve()
    tracked = git_tracked(root) if (root / ".git").exists() else set()
    if args.tracked and not tracked:
        print("⚠️ 目标不是 git 仓库或没有已跟踪文件，--tracked 退化为全量扫描")

    SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "build", ".hvigor", ".idea"}
    SKIP_FILES = {Path(__file__).name, "scan-secrets.py"}
    TEXT_EXT = {".py", ".md", ".json", ".yml", ".yaml", ".txt", ".sh", ".js", ".ts",
                ".ets", ".json5", ".toml", ".cfg", ".ini", ".env", ".gitignore", ""}

    hard, soft = [], []
    scanned, skipped_tracked = 0, []
    for p in sorted(root.rglob("*")):
        if p.is_dir() or any(d in p.parts for d in SKIP_DIRS):
            continue
        rel = str(p.relative_to(root))
        if args.tracked and tracked and rel not in tracked:
            continue
        if p.name in SKIP_FILES or p.suffix not in TEXT_EXT:
            if rel in tracked:
                skipped_tracked.append(rel)
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        scanned += 1
        for name, frag, line in scan_text(text, args.extra_pattern):
            (hard if rel in tracked else soft).append((rel, name, frag, line))

    print(f"扫描 {scanned} 个文本文件" + (f"（其中 git 已跟踪 {len(tracked)} 个）" if tracked else ""))
    if skipped_tracked:
        print(f"⚠️ 有 {len(skipped_tracked)} 个『已跟踪』文件按跳过规则未扫描 —— 确认是预期的（如扫描器自身）：")
        for s in skipped_tracked:
            print(f"    {s}")
    if hard:
        print(f"\n🔴 危险：命中且已被 git 跟踪（{len(hard)} 处）—— 推送前必须处理")
        for rel, name, frag, line in hard[:40]:
            print(f"    {rel}:{line}  [{name}] {frag[:40]}")
    if soft:
        print(f"\n🟡 提示：命中但未被 git 跟踪（{len(soft)} 处）—— 请确认 .gitignore 会挡住它们")
        seen = set()
        for rel, name, frag, line in soft:
            key = (rel, name)
            if key in seen:
                continue
            seen.add(key)
            print(f"    {rel}:{line}  [{name}] {frag[:40]}")
    if not hard and not soft:
        print("✅ 未发现敏感内容")
    print(f"\n结论：{'🔴 不安全，先处理上面红线' if hard else '🟢 无「已跟踪』的敏感命中'}")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
