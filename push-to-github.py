#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
万象 · 一键发布到 GitHub（建仓 → 门禁 → 推送 → 触发 Actions → 验证产物）

为什么需要它：
  GitHub 网页在国内不稳（实测首页 curl 常超时、浏览器 2.1s 但会卡），而 api.github.com 稳定 0.5s。
  所以本脚本用 API 完成网页上要做的一切，你只需要提供一次 Personal Access Token。

用法：
  python3 push-to-github.py                     # 交互式（会安全提示输入 token）
  GH_TOKEN=ghp_xxx python3 push-to-github.py    # 用环境变量传 token
  python3 push-to-github.py --repo other-name   # 换仓库名
  python3 push-to-github.py --skip-verify       # 不等待 Actions 结果
  python3 push-to-github.py --dry-run           # 只检查不写任何东西

安全约定：
  - token 只存在于本次进程内存 + 与 GitHub 的 HTTPS 请求中；
  - 绝不写入 .git/config、绝不打印、绝不落盘；
  - 推送用「一次性 URL」形式（git 不会记住它）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
WORKFLOW_FILE = "update-feeds.yml"
DEFAULT_REPO = "wanxiang-feeds"
REPO_DESC = "万象资讯 App 的信息源产物（GitHub Actions 定时生成 JSON Feed）"

C_OK, C_WARN, C_ERR, C_DIM, C_RST = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def say(msg=""):
    print(msg, flush=True)


def step(n, total, title):
    say(f"\n{C_DIM}[{n}/{total}]{C_RST} {title}")


def ok(msg):
    say(f"  {C_OK}✅{C_RST} {msg}")


def warn(msg):
    say(f"  {C_WARN}⚠️ {C_RST} {msg}")


def err(msg):
    say(f"  {C_ERR}❌{C_RST} {msg}")


def api(method: str, path: str, token: str, payload=None, timeout=30):
    """返回 (status, 解析后的 body 或原始文本)。"""
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "wanxiang-publisher")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return 0, str(e)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ─────────────────────────── 步骤实现 ───────────────────────────

def check_env():
    problems = []
    if run(["git", "--version"]).returncode != 0:
        problems.append("未找到 git")
    return problems


def get_token(args) -> str:
    tok = args.token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        ok("已从参数/环境变量读取 token")
        return tok.strip()
    say("  需要一个 GitHub Personal Access Token（只用一次，不会保存）")
    say(f"  {C_DIM}生成地址: https://github.com/settings/tokens → Generate new token (classic) → 勾 repo{C_RST}")
    say(f"  {C_DIM}输入时不会回显（粘贴后按回车）{C_RST}")
    try:
        import getpass
        tok = getpass.getpass("  Token: ").strip()
    except Exception:
        tok = input("  Token: ").strip()
    return tok


def verify_token(token):
    st, body = api("GET", "/user", token)
    if st == 200 and isinstance(body, dict):
        return body.get("login")
    if st == 401:
        err("token 无效或已过期（401）")
    elif st == 0:
        err(f"连不上 api.github.com：{body}")
    else:
        err(f"验证失败 HTTP {st}: {str(body)[:200]}")
    return None


def ensure_repo(token, owner, repo, dry_run=False):
    st, body = api("GET", f"/repos/{owner}/{repo}", token)
    if st == 200 and isinstance(body, dict):
        private = body.get("private")
        if private:
            warn(f"仓库已存在但是【私有】—— Actions 每月仅 2000 分钟，本任务约需 7200 分钟，会跑一半就停")
            warn(f"建议改成公开：Settings → Danger Zone → Change visibility → Make public")
        else:
            ok(f"仓库已存在且是公开的")
        return True, False
    if st == 404:
        if dry_run:
            ok(f"仓库不存在（dry-run 不创建）")
            return True, True
        st2, body2 = api("POST", "/user/repos", token, {
            "name": repo,
            "description": REPO_DESC,
            "private": False,
            "auto_init": False,
            "has_issues": True,
            "has_wiki": False,
        })
        if st2 == 201:
            ok(f"已创建公开仓库 https://github.com/{owner}/{repo}")
            return True, True
        err(f"创建仓库失败 HTTP {st2}: {str(body2)[:300]}")
        return False, False
    err(f"查询仓库失败 HTTP {st}: {str(body)[:200]}")
    return False, False


def gate(root: Path):
    """凭据门禁：先自检，再扫（先 add 再扫，否则新增文件漏扫）。"""
    scanner = root / "scripts" / "scan-secrets.py"
    if not scanner.exists():
        warn("找不到 scripts/scan-secrets.py，跳过门禁（不建议）")
        return True
    py = sys.executable or "python3"
    st = run([py, str(scanner), "--selftest"])
    if st.returncode != 0:
        err("门禁工具自检未通过 —— 不可采信它的结果，中止")
        print(st.stdout[-800:])
        return False
    ok("门禁工具自检通过")
    st = run([py, str(scanner), ".", "--tracked"], cwd=str(root))
    print("\n".join("    " + l for l in st.stdout.strip().splitlines()[-6:]))
    if st.returncode != 0:
        err("门禁扫描发现『已被 git 跟踪』的敏感内容，中止推送")
        return False
    ok("门禁扫描通过")
    return True


def git_commit(root: Path, repo_url_name: str):
    def g(*a, check=True):
        r = run(["git", *a], cwd=str(root))
        if check and r.returncode != 0:
            raise RuntimeError(f"git {' '.join(a)} 失败:\n{r.stderr.strip()}")
        return r

    if not (root / ".git").exists():
        g("init", "-q")
        ok("已初始化 git 仓库")
    g("add", "-A")
    n = len(g("diff", "--cached", "--name-only").stdout.split())
    ok(f"暂存 {n} 个文件")
    if g("diff", "--cached", "--quiet", check=False).returncode != 0:
        g("-c", "user.name=wanxiang-bot",
          "-c", "user.email=wanxiang-bot@users.noreply.github.com",
          "commit", "-q", "-m", "init: 万象信息源构建（GitHub Actions 定时抓取 → JSON Feed）")
        ok("已提交")
    else:
        ok("无新变化，跳过提交")
    g("branch", "-M", "main")
    return True


def push(token, owner, repo, root: Path):
    """用一次性 URL 推送，token 不写入 .git/config。"""
    remote = f"https://github.com/{owner}/{repo}.git"
    # 清理可能存在的旧 origin（避免把 token 带进去）
    run(["git", "remote", "remove", "origin"], cwd=str(root))
    run(["git", "remote", "add", "origin", remote], cwd=str(root))
    authed = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    r = run(["git", "push", "-q", authed, "main:main", "--force"], cwd=str(root))
    if r.returncode != 0:
        err(f"推送失败：{r.stderr.strip()[:400]}")
        if "403" in r.stderr or "denied" in r.stderr.lower():
            say(f"  {C_DIM}提示：token 需要勾选 repo 权限；若是细粒度 token，需给 Contents: Read and write{C_RST}")
        return False
    ok(f"已推送到 {remote}")
    # 复核：确保 token 没留在本地配置里
    cfg = root / ".git" / "config"
    if cfg.exists() and token[:12] in cfg.read_text(errors="ignore"):
        err("检测到 token 残留在 .git/config，请手动清理")
        return False
    return True


def trigger_workflow(token, owner, repo):
    st, body = api("POST", f"/repos/{owner}/{repo}/actions/workflows/{WORKFLOW_FILE}/dispatches",
                   token, {"ref": "main"})
    if st in (204, 201, 200):
        ok("已触发 Actions 工作流")
        return True
    if st == 404:
        warn("找不到工作流（可能还没被 GitHub 索引，或文件名不符）—— 可稍后在网页 Actions 页手动 Run workflow")
        return False
    warn(f"触发失败 HTTP {st}: {str(body)[:200]}")
    return False


def wait_and_verify(token, owner, repo, max_wait=420):
    """轮询最近一次 run，然后验证产物 feeds/index.json 是否更新。"""
    deadline = time.time() + max_wait
    run_id, seen = None, False
    while time.time() < deadline:
        st, body = api("GET", f"/repos/{owner}/{repo}/actions/runs?per_page=1", token)
        if st == 200 and isinstance(body, dict) and body.get("workflow_runs"):
            r0 = body["workflow_runs"][0]
            run_id = r0["id"]
            status, concl = r0.get("status"), r0.get("conclusion")
            if status == "completed":
                if concl == "success":
                    ok(f"工作流运行成功（run #{r0['run_number']}）")
                    break
                err(f"工作流失败（{concl}）—— 日志：https://github.com/{owner}/{repo}/actions/runs/{run_id}")
                return False
            else:
                if not seen:
                    say(f"  {C_DIM}工作流运行中… (状态: {status}){C_RST}")
                    seen = True
                time.sleep(15)
                continue
        else:
            time.sleep(10)
    else:
        warn("等待超时，请自行到 Actions 页查看")
        return False

    st, body = api("GET", f"/repos/{owner}/{repo}/contents/feeds/index.json", token)
    if st == 200 and isinstance(body, dict):
        ok("产物已生成：feeds/index.json 存在")
        say(f"  {C_DIM}raw 地址（App 读取用）：{C_RST}")
        say(f"    https://raw.githubusercontent.com/{owner}/{repo}/main/feeds/")
        say(f"    https://ghproxy.net/https://raw.githubusercontent.com/{owner}/{repo}/main/feeds/")
        return True
    warn("产物 feeds/index.json 还没出现 —— 稍等 1~2 分钟再看仓库首页")
    return False


# ─────────────────────────── 主流程 ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description="万象 · 一键发布到 GitHub")
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"仓库名（默认 {DEFAULT_REPO}）")
    ap.add_argument("--token", default="", help="GitHub token（推荐用 GH_TOKEN 环境变量或交互输入）")
    ap.add_argument("--skip-verify", action="store_true", help="不等待 Actions 结果")
    ap.add_argument("--dry-run", action="store_true", help="只检查，不创建/不推送")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    say("═" * 52)
    say(f" 万象 · 一键发布到 GitHub")
    say(f" 目录: {root}")
    say(f" 目标: https://github.com/<你的账号>/{args.repo}")
    say("═" * 52)

    total = 6
    step(1, total, "环境检查")
    problems = check_env()
    if problems:
        for p in problems:
            err(p)
        return 1
    ok(f"git 就绪，Python {sys.version.split()[0]}")

    step(2, total, "获取并验证 GitHub token")
    token = get_token(args)
    if not token:
        err("未提供 token，中止")
        return 1
    login = verify_token(token)
    if not login:
        return 1
    ok(f"token 有效，账号：{login}")
    if login.lower() == args.repo.lower():
        warn("账号名和仓库名相同，确认没搞混")

    step(3, total, "检查仓库并验证门禁")
    exists, created = ensure_repo(token, login, args.repo, dry_run=args.dry_run)
    if not exists:
        return 1
    if args.dry_run:
        say(f"  {C_DIM}dry-run 模式，后续步骤跳过{C_RST}")
        if not gate(root):
            return 1
        ok("dry-run 完成，一切正常")
        return 0

    step(4, total, "提交并推送（含凭据门禁）")
    try:
        git_commit(root, args.repo)
    except RuntimeError as e:
        err(str(e))
        return 1
    if not gate(root):
        return 1
    if not push(token, login, args.repo, root):
        return 1

    step(5, total, "触发 Actions 工作流")
    triggered = trigger_workflow(token, login, args.repo)

    step(6, total, "验证产物")
    if args.skip_verify or not triggered:
        say(f"  {C_DIM}跳过等待。稍后自行查看：https://github.com/{login}/{args.repo}/actions{C_RST}")
        verified = None
    else:
        verified = wait_and_verify(token, login, args.repo)

    say()
    say("═" * 52)
    if verified is True:
        say(f" {C_OK}🎉 全部完成 —— 仓库已在自动运行{C_RST}")
    elif verified is False:
        say(f" {C_WARN}⚠️ 推送成功，但产物验证未通过（多为首次运行较慢）{C_RST}")
        say(f"   去看看：https://github.com/{login}/{args.repo}/actions")
    else:
        say(f" {C_OK}✅ 推送完成{C_RST}")
    say()
    say(f" 仓库:  https://github.com/{login}/{args.repo}")
    say(f" 流水:  https://github.com/{login}/{args.repo}/actions")
    say(f" 产物:  https://raw.githubusercontent.com/{login}/{args.repo}/main/feeds/")
    say()
    say(f" 下一步：把仓库地址发我，我配好万象 App 的「热榜」频道")
    say("═" * 52)
    return 0 if verified is not False else 2


if __name__ == "__main__":
    sys.exit(main())
