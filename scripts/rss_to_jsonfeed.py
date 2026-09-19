#!/usr/bin/env python3
"""
万象 · 热榜源转换器（DailyHotApi RSS → JSON Feed 1.1）

为什么需要它：
  DailyHotApi 输出 RSS 2.0 XML，而万象只认 JSON Feed 1.1（App 端刻意避开 ArkTS 的 XML 解析坑）。
  本脚本把 RSS 转成 JSON Feed，并把 media:content 的图片塞进 content_html ——
  这样万象的 ContentCleaner.firstImage 能直接抽出列表缩略图。

用法：
  # 用配置文件（推荐，GitHub Actions 就是这么调）
  python3 rss_to_jsonfeed.py --base http://127.0.0.1:6688 --out feeds --config config/sources.json

  # 临时指定平台
  python3 rss_to_jsonfeed.py --base http://127.0.0.1:6688 --out feeds --sources "zhihu=知乎热榜,weibo=微博热搜"

  # 都不给 → 用脚本内置的默认平台集
"""
import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

# 默认平台（配置文件缺失时的兜底）
DEFAULT_SOURCES = {
    "zhihu": "知乎热榜",
    "weibo": "微博热搜",
    "bilibili": "哔哩哔哩热榜",
    "juejin": "掘金热榜",
    "github": "GitHub Trending",
    "sspai": "少数派热门",
    "36kr": "36氪热榜",
    "ithome": "IT之家热榜",
    "douyin": "抖音热榜",
    "toutiao": "今日头条热榜",
    "thepaper": "澎湃热榜",
}

UA = {"User-Agent": "Mozilla/5.0 (compatible; WanxiangFeedBot/1.0)"}


def strip_cdata(s: str) -> str:
    s = s.strip()
    if s.startswith("<![CDATA["):
        s = s[len("<![CDATA["):]
    if s.endswith("]]>"):
        s = s[:-3]
    return s.strip()


def tag(it: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>([\s\S]*?)</{name}>", it)
    return strip_cdata(m.group(1)) if m else ""


def fetch_rss(base: str, platform: str, timeout: int = 20) -> str:
    url = f"{base.rstrip('/')}/{platform}?rss=true"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def rss_to_jsonfeed(xml: str, name: str, platform: str) -> dict:
    """RSS 2.0 → JSON Feed 1.1（万象可直接解析）"""
    ch_title = tag(xml, "title") or name
    m = re.search(r"<channel>[\s\S]*?<link>([\s\S]*?)</link>", xml)
    home = strip_cdata(m.group(1)) if m else ""

    items = []
    for it in re.findall(r"<item>([\s\S]*?)</item>", xml):
        t = tag(it, "title")
        link = tag(it, "link")
        desc = tag(it, "description")
        guid = tag(it, "guid") or link or t
        pub = tag(it, "pubDate")
        mi = re.search(r'<media:(?:content|thumbnail)[^>]*url="([^"]+)"', it)
        img = mi.group(1) if mi else ""

        parts = []
        if desc and desc != t:
            parts.append(f"<p>{desc}</p>")
        if img:
            parts.append(f'<img src="{img}" />')
        content_html = "".join(parts) if parts else f"<p>{t}</p>"

        items.append({
            "id": f"{platform}-{guid}",
            "url": link,
            "title": t,
            "content_html": content_html,
            "date_published": pub,
        })
    return {
        "version": "https://jsonfeed.org/version/1.1",
        "title": ch_title,
        "home_page_url": home or "https://github.com/imsyy/DailyHotApi",
        "description": f"{name}（via DailyHotApi · 生成于 {time.strftime('%Y-%m-%d %H:%M:%S')}）",
        "items": items,
    }


def load_sources(args) -> dict:
    """优先级：--sources > --config > 内置默认"""
    if args.sources:
        out = {}
        for pair in args.sources.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                out[k.strip()] = v.strip()
        return out
    if args.config:
        p = Path(args.config)
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            entries = cfg.get("feeds", cfg if isinstance(cfg, list) else [])
            out = {}
            for e in entries:
                if e.get("enabled", True) and e.get("platform"):
                    out[e["platform"]] = e.get("name", e["platform"])
            if out:
                print(f"从 {args.config} 读取到 {len(out)} 个启用的平台")
                return out
        print(f"⚠️ 配置文件 {args.config} 不存在或为空，改用内置默认平台集")
    return DEFAULT_SOURCES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:6688")
    ap.add_argument("--out", default="./feeds")
    ap.add_argument("--sources", default="")
    ap.add_argument("--config", default="")
    args = ap.parse_args()

    sources = load_sources(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    report = []
    for platform, name in sources.items():
        try:
            xml = fetch_rss(args.base, platform)
            feed = rss_to_jsonfeed(xml, name, platform)
            fp = out / f"{platform}.json"
            fp.write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")
            thumbs = sum(1 for i in feed["items"] if "<img" in i["content_html"])
            report.append({"platform": platform, "name": name,
                           "items": len(feed["items"]), "thumbs": thumbs,
                           "file": f"{platform}.json", "bytes": fp.stat().st_size})
            print(f"  ✅ {platform:<12} {name:<16} {len(feed['items']):>3} 条 | 带图 {thumbs:>3} | {fp.stat().st_size:>7}B")
        except Exception as e:
            print(f"  ❌ {platform:<12} {name:<16} 失败: {type(e).__name__} {e}")
        time.sleep(0.4)

    index = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "万象热榜索引",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_items": sum(r["items"] for r in report),
        "feeds": report,
    }
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n共 {len(report)} 个 feed、{index['total_items']} 条 → {out}/")
    if not report:
        raise SystemExit("❌ 没有任何 feed 生成成功")


if __name__ == "__main__":
    main()
