#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""万象 · 给 GitHub 仓库配置 Actions Secrets（用 API，无需网页操作）

用途：把 Gitee 同步所需的 GITEE_USER / GITEE_TOKEN 写进仓库的 Actions Secrets，
      这样 Actions 每次跑完会自动把 feeds/ 同步到 Gitee（国内直连通道）。

用法：
  GH_TOKEN=<你的GitHub令牌> GITEE_USER=gfcat GITEE_TOKEN=<Gitee令牌> \
    python3 set_github_secrets.py [--repo wanxiang-feeds]

安全约定：
  - 所有凭据只从环境变量读，绝不写文件、绝不打印；
  - 输出只报告「是否配置成功」，不回显任何值。
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"


def api(method, path, token, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "wanxiang-secrets")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="wanxiang-feeds")
    ap.add_argument("--owner", default="")
    args = ap.parse_args()

    gh = os.environ.get("GH_TOKEN", "").strip()
    if not gh:
        print("❌ 需要 GH_TOKEN 环境变量（GitHub 令牌）")
        return 1

    st, me = api("GET", "/user", gh)
    if st != 200 or not isinstance(me, dict):
        print(f"❌ GitHub 令牌无效: HTTP {st}")
        return 1
    owner = args.owner or me.get("login")
    repo = args.repo
    print(f"  仓库: {owner}/{repo}")

    # 待配置的 secrets（值只从环境变量取）
    wanted = {}
    if os.environ.get("GITEE_USER", "").strip():
        wanted["GITEE_USER"] = os.environ["GITEE_USER"].strip()
    if os.environ.get("GITEE_TOKEN", "").strip():
        wanted["GITEE_TOKEN"] = os.environ["GITEE_TOKEN"].strip()
    if not wanted:
        print("❌ 没提供任何待配置的 secret（需要 GITEE_USER / GITEE_TOKEN 环境变量）")
        return 1

    print(f"  待配置: {', '.join(sorted(wanted.keys()))}（值不回显）")
    print()

    st, keyinfo = api("GET", f"/repos/{owner}/{repo}/actions/secrets/public-key", gh)
    if st != 200 or not isinstance(keyinfo, dict):
        msg = keyinfo.get("message") if isinstance(keyinfo, dict) else str(keyinfo)[:120]
        print(f"  ❌ 取公钥失败: HTTP {st} {msg}")
        if st == 404:
            print("     检查：仓库名是否正确 / 令牌是否有 repo 权限")
        return 1
    key_id = keyinfo["key"]
    pub_key = keyinfo["key_id"]
    print(f"  ✅ 已取到仓库公钥 (key_id={pub_key[:12]}…)")

    try:
        from nacl import encoding, public
    except ImportError:
        print("  ❌ 缺少 PyNaCl：pip install pynacl")
        return 1

    pk = public.PublicKey(key_id.encode(), encoding.Base64Encoder())

    ok_n = 0
    for name, value in wanted.items():
        sealed = public.SealedBox(pk).encrypt(value.encode())
        enc = base64.b64encode(sealed).decode()
        st, body = api("PUT", f"/repos/{owner}/{repo}/actions/secrets/{name}", gh,
                       {"encrypted_value": enc, "key_id": pub_key})
        if st in (201, 204):
            print(f"  ✅ {name} 已配置")
            ok_n += 1
        else:
            msg = body.get("message") if isinstance(body, dict) else str(body)[:120]
            print(f"  ❌ {name} 配置失败: HTTP {st} {msg}")

    print()
    print(f"  完成 {ok_n}/{len(wanted)}")
    if ok_n:
        print("  下一步：手动触发一次 Actions，跑完就会自动同步到 Gitee")
        print(f"    https://github.com/{owner}/{repo}/actions")
    return 0 if ok_n == len(wanted) else 1


if __name__ == "__main__":
    sys.exit(main())
