# 万象 · 信息源云端构建仓库

这个仓库不存代码，只有一个作用：**用 GitHub Actions 定时抓取信息源，把结果变成万象 App 能直接读的 JSON 文件**。

```
GitHub Actions（每 30 分钟）
   ├─ DailyHotApi  → 抓 11+ 平台热榜（知乎/微博/B站/头条/抖音/36氪/IT之家…）
   └─ wewe-rss     → 抓你订阅的微信公众号文章（全文）
              ↓  统一转成 JSON Feed 1.1
        feeds/*.json  提交回本仓库
              ↓
   万象 App 通过 ghproxy.net / jsDelivr 拉取 → 显示在「热榜」「公众号」频道
```

## 为什么是这个方案

| 需求 | 怎么满足 |
|---|---|
| 不租服务器、不要家里机器常开 | GitHub Actions 是云端定时任务，公开仓库免费且时长不限 |
| 要知乎热榜（公开 RSSHub 拿不到，503） | DailyHotApi 直接有，且不需要登录 |
| 要公众号文章（要能读全文） | wewe-rss 支持 `FEED_MODE=fulltext` 全文输出 |
| 万象不改代码就能用 | 产物是标准 JSON Feed 1.1，与万象现有源格式完全一致 |

**已知代价（如实说明）**：GitHub 免费版的 `schedule` 不保证准时 —— 高峰期可能延迟 5~30 分钟，极端情况会跳过一轮。热榜场景够用；要"分钟级实时"必须自建。

---

## 一、部署（5 分钟，不需要任何密钥）

1. 在 GitHub 新建一个**公开仓库**（Public —— 私有仓库 Actions 每月只有 2000 分钟，公开仓库不限量且本仓库不含敏感信息）
2. 把本目录推上去：
   ```bash
   cd github-feeds
   git init && git add -A
   git commit -m "init: 万象信息源构建"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```
3. 打开仓库的 **Actions** 标签页 → 左侧选「更新万象信息源」→ 右侧 **Run workflow** 手动跑一次
4. 跑完（约 3~6 分钟）后，仓库里会出现 `feeds/` 目录，里面有 `zhihu.json`、`weibo.json`… 和 `index.json`

之后每 30 分钟自动更新，不用管。

### 想增删平台？
改 `config/sources.json`：`enabled: false` 关掉某个平台，或从注释里挑其他平台打开（DailyHotApi 支持 72 个）。推上去后 Actions 会自动重跑。

---

## 二、公众号接入（wewe-rss，需要一次性登录）

wewe-rss 靠**微信读书**账号读取公众号文章，所以必须有登录态。登录态存在 SQLite 数据库里，把它提交到仓库，Actions 每次复用即可。

**一次性操作（在你自己的电脑上做，本机有 Docker 就行）：**

```bash
mkdir -p ~/wewe-rss && cd ~/wewe-rss && mkdir -p data
docker run -d --name wewe-local -p 4000:4000 \
  -e DATABASE_TYPE=sqlite \
  -e AUTH_CODE=你自己设一个授权码 \
  -e SERVER_ORIGIN_URL=http://localhost:4000 \
  -v "$PWD/data:/app/data" \
  cooderl/wewe-rss-sqlite:latest
```

然后浏览器打开 `http://localhost:4000`：
1. 用**微信读书扫码登录**
2. 在「公众号管理」里搜索并**添加你要订阅的公众号**
3. 等它抓一轮（或点手动更新）

完成后，把登录态数据库复制进仓库：

```bash
cp ~/wewe-rss/data/wewe-rss.db <本仓库>/data/wewe-rss.db
cd <本仓库> && git add data/ && git commit -m "add: wewe-rss 登录态" && git push
```

最后启用这个 Job：
- 仓库 **Settings → Secrets and variables → Actions**
  - **Variables** 页新增 `ENABLE_WEWE` = `true`
  - **Secrets** 页新增 `WEWE_AUTH_CODE` = 你上面设的授权码

**⚠️ 登录态会过期**（通常数周到数月）。过期的表现：Actions 里「公众号订阅」Job 报「条目为空」。这时在本地重新跑一遍上面的 docker、重新扫码，把新的 `data/wewe-rss.db` 覆盖提交即可。

---

## 三、万象 App 端接入

产物路径（GitHub 上的原始地址）：
```
https://raw.githubusercontent.com/<用户名>/<仓库名>/main/feeds/zhihu.json
```

国内直连 `raw.githubusercontent.com` 不稳（实测超时），所以要**通过 CDN 中转**。实测可用：

| 通道 | 地址模板 | 实测 |
|---|---|---|
| **ghproxy.net** | `https://ghproxy.net/https://raw.githubusercontent.com/<用户>/<仓库>/main` | ✅ 200，实时 |
| fastly.jsdelivr.net | `https://fastly.jsdelivr.net/gh/<用户>/<仓库>@main` | ✅ 200（有 CDN 缓存，时效性略差） |

**接入方式**：编辑万象工程里的 `sources.json`，加一个频道和若干源。以热榜频道为例：

```json
{
  "channels": [
    { "key": "hot", "name": "热榜" }
  ],
  "instances": [
    "https://ghproxy.net/https://raw.githubusercontent.com/<用户>/<仓库>/main",
    "https://rsshub.ktachibana.party",
    "https://rsshub.woodland.cafe"
  ],
  "sources": [
    { "id": "hot-zhihu", "name": "知乎热榜", "channel": "hot",
      "route": "/feeds/zhihu.json", "enabled": true },
    { "id": "hot-weibo", "name": "微博热搜", "channel": "hot",
      "route": "/feeds/weibo.json", "enabled": true },
    { "id": "wx-all", "name": "微信公众号", "channel": "wx",
      "route": "/feeds/wx-all.json", "enabled": true }
  ]
}
```

> 万象的取数逻辑是 `实例 + 路由 + '?format=json'`，多余的查询串参数无害，所以上面这样配置即可，**App 代码无需改动**。

---

## 四、常见问题

**Q：Actions 跑失败，报 `服务未起来`**
看日志里 `/tmp/dha.log` 的内容。最常见是 npm 安装超时 → 重跑一次通常就好。

**Q：热榜条目点进去为什么要跳浏览器？**
热榜的本质是**链接列表**（知乎热榜就是"哪个问题在热"），平台本身不提供正文。想要"点开就能读全文"，用**公众号频道**（wewe-rss 输出全文）。两者定位不同：热榜=知道大家在讨论什么，公众号=深度阅读。

**Q：能不能加新闻类（不是热榜）？**
可以，但这类更适合继续用 RSSHub（本仓库的 DailyHotApi 定位是热榜）。若想在这里也加，编辑 `config/sources.json` 里的平台即可。

**Q：仓库公开会不会泄露隐私？**
本仓库只有公开的热榜数据和你的公众号订阅列表。**公众号阅读记录本身在微信读书体系内，不涉及隐私内容**。若你介意订阅列表公开，把仓库设为私有 —— 代价是 Actions 每月 2000 分钟限额（本任务每次约 5 分钟，30 分钟一轮 ≈ 每月 7200 分钟，会超），此时建议把频率降到每小时一次（改 workflow 里的 cron 为 `7 * * * *`）。
