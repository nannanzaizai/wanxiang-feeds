#!/usr/bin/env python3
"""
万象 · 热榜聚合器（多个平台 feed → 一个 all.json）

为什么需要它（2026-10-15 实测依据）：
  App 原来要读 11 个平台文件 = 11 次 HTTP 请求。而产物通道本身是抖动的
  （实测同一时刻 gh-proxy 约一半请求被网络层瞬断、jsdelivr 全挂、Gitee 部分文件 451），
  源越多 → 撞上失败路径的概率越大（每个源各自降级、各自超时）。
  合并成一个文件后：**1 次请求拿全部热榜**，请求数和失败面同时降到 1/11。

条目里带两个非标准字段（App 端 FeedParser 已支持，见 FeedParser.ets）：
  _source  平台显示名（如「知乎热榜」）—— 合并后列表卡片仍能显示各平台来源标签
  _platform 平台 key（如 zhihu）—— 便于排查与将来按平台过滤

用法：
  python3 scripts/merge_feeds.py --feeds-dir feeds --config config/sources.json
"""
import argparse
import json
import time
from pathlib import Path


def load_enabled_order(cfg_path: str) -> list:
    """按 config/sources.json 的顺序取启用平台（顺序影响列表里各平台的相对次序）"""
    p = Path(cfg_path)
    if not p.exists():
        return []
    cfg = json.loads(p.read_text(encoding="utf-8"))
    entries = cfg.get("feeds", cfg if isinstance(cfg, list) else [])
    out = []
    for e in entries:
        if e.get("enabled", True) and e.get("platform"):
            out.append((e["platform"], e.get("name", e["platform"])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeds-dir", default="feeds")
    ap.add_argument("--config", default="config/sources.json")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    feeds_dir = Path(args.feeds_dir)
    out_path = Path(args.out) if args.out else feeds_dir / "all.json"

    order = load_enabled_order(args.config)
    if not order:
        # 配置读不到就按目录里现有文件（排除 index/all）兜底，避免整条流水线白跑
        order = [(f.stem, f.stem) for f in sorted(feeds_dir.glob("*.json"))
                 if f.stem not in ("index", "all")]

    merged_items = []
    detail = []
    for platform, name in order:
        fp = feeds_dir / f"{platform}.json"
        if not fp.exists():
            print(f"  ⚠️ {platform:<12} 缺少 {fp.name}，跳过")
            continue
        try:
            feed = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠️ {platform:<12} 解析失败: {type(e).__name__} {e}")
            continue
        items = feed.get("items", [])
        for it in items:
            merged_items.append({
                "id": it.get("id", ""),
                "url": it.get("url", ""),
                "title": it.get("title", ""),
                "content_html": it.get("content_html", ""),
                "date_published": it.get("date_published", ""),
                "_source": name,
                "_platform": platform,
            })
        thumbs = sum(1 for i in items if "<img" in (i.get("content_html") or ""))
        detail.append({"platform": platform, "name": name,
                       "items": len(items), "thumbs": thumbs})
        print(f"  + {platform:<12} {name:<16} 并入 {len(items):>3} 条")

    if not merged_items:
        raise SystemExit("❌ 没有任何平台可并入，拒绝写出空的 all.json（保留上一版）")

    merged = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "万象 · 热榜聚合",
        "home_page_url": "https://github.com/nannanzaizai/wanxiang-feeds",
        "description": (f"11 平台热榜聚合（via DailyHotApi · 生成于 "
                        f"{time.strftime('%Y-%m-%d %H:%M:%S')}）"),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platforms": detail,
        "items": merged_items,
    }
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ 聚合完成：{len(detail)} 平台 / {len(merged_items)} 条 / "
          f"{out_path.stat().st_size} B → {out_path}")

    # 把聚合结果登记进 index.json（云端自检用：一次 curl 即可看全貌）
    idx_path = feeds_dir / "index.json"
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            idx["merged"] = {"file": out_path.name, "items": len(merged_items),
                             "bytes": out_path.stat().st_size,
                             "platforms": len(detail)}
            idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"   已在 {idx_path.name} 里登记 merged 段落")
        except Exception as e:
            print(f"   ⚠️ 更新 index.json 失败（不影响 all.json）: {type(e).__name__} {e}")


if __name__ == "__main__":
    main()
