# 万象 · 信息源云端构建仓库

这个仓库不存代码，只做一件事：**用 GitHub Actions 定时抓取信息源，产出万象 App 能直接读的 JSON 文件**。

```
GitHub Actions（每 30 分钟，公开仓库额度无限）
   ├─ DailyHotApi  → 抓 11+ 平台热榜（知乎/微博/B站/头条/抖音/36氪/IT之家/少数派…）
   └─ wewe-rss     → 抓订阅的微信公众号文章（全文输出）
              ↓  统一转成 JSON Feed 1.1
        feeds/*.json
              ↓  双通道发布
   ① GitHub raw  ←→ ghproxy.net 转发（实测 5/5 成功，0.5~0.7s）
   ② Gitee 镜像  ←→ 国内直连（~0.1s，需仓库公开）
              ↓
   万象 App（实例轮换自动降级：Gitee 优先，失败回落 ghproxy）
```

## 为什么是这个方案

| 需求 | 满足方式 |
|---|---|
| 不租服务器、不要家里机器常开 | GitHub Actions 云端定时任务，**公开仓库免费且时长无限** |
| 要知乎热榜（公开 RSSHub 拿不到，503） | DailyHotApi 自带，无需登录 |
| 要公众号文章，且能读全文 | wewe-rss `FEED_MODE=fulltext` 输出全文 |
| 万象不改代码就能用 | 产物是标准 **JSON Feed 1.1**，与万象现有源格式一致 |
| 国内取数要快 | Gitee 镜像通道（0.1s）；没开通也有 ghproxy 兜底 |

**已知代价（如实说明）**：GitHub 免费版 `schedule` 不保证准时 —— 高峰期延迟 5~30 分钟，极端情况跳过一轮。热榜场景够用；要"分钟级实时"只能自建（本方案已排除）。

---

## 一、部署（一条命令，无需先建仓库）

> 前提：一个 GitHub **Personal Access Token**（只勾 `repo` 权限即可）
> 生成：https://github.com/settings/tokens → Generate new token (classic) → 勾 `repo`

```bash
cd github-feeds
python3 push-to-github.py          # 会安全提示输入 token（不回显、不落盘）
```

脚本自动完成全流程：

| 步骤 | 做什么 |
|---|---|
| 1 | 检查 git / Python 环境 |
| 2 | 验证 token，用 API 识别你的账号名 |
| 3 | 检查仓库，**不存在就用 API 自动创建公开仓库**（不必去点网页 —— GitHub 网页在国内不稳，API 稳定 0.5s） |
| 4 | 跑**凭据门禁**（工具自检 + 扫描），不过就不推 |
| 5 | 提交并推送（token 用一次性 URL，**不写入 `.git/config`**） |
| 6 | 触发 Actions 工作流并轮询结果，最后验证 `feeds/index.json` 是否生成 |

常用变体：

```bash
GH_TOKEN=ghp_xxx python3 push-to-github.py    # 用环境变量传 token
python3 push-to-github.py --dry-run           # 只检查环境/仓库/门禁，不写任何东西
python3 push-to-github.py --skip-verify       # 推完就走，不等待 Actions
python3 push-to-github.py --repo 别的仓库名    # 换仓库名
bash push-to-github.sh                        # 等价（薄包装）
```

跑完后，仓库每 30 分钟自动更新。

### 增删平台
改 `config/sources.json`：`enabled: false` 关掉；或从注释行里挑其它平台打开（DailyHotApi 支持 72 个）。推送后 Actions 自动重跑。

---

## 二、Gitee 镜像通道（可选，国内直连快 10 倍）

**注意 Gitee 的政策限制**：Gitee 要求账号**完成 2FA 或绑定第三方账号**后才允许创建**公开**仓库，否则建出来的仓库是私有的，而私有仓库的 raw 端点**连 token 都拒绝访问**（实测 403），只能走 API，不适合 App 直连。

所以要用 Gitee 通道，先做其中一件事：
- Gitee「个人设置 → 安全设置」**开启 2FA**（推荐），或
- 绑定第三方账号（微信 / QQ / GitHub 等任选其一）

然后：
1. 在 Gitee 建**公开**仓库 `wanxiang-feeds`（与 GitHub 同名方便管理）
2. 在 GitHub 仓库 **Settings → Secrets and variables → Actions**：
   - **Secrets** 页新增 `GITEE_USER` = 你的 Gitee 用户名
   - **Secrets** 页新增 `GITEE_TOKEN` = Gitee 私人令牌（**只勾 projects 权限即可**）
   - **Variables** 页新增 `GITEE_REPO` = `wanxiang-feeds`（可选，默认就是这个名字）

配好后，每次 Actions 跑完会自动把 `feeds/` 强推到 Gitee。没配也不影响 —— 只是 App 走 ghproxy 通道（慢一点但能用）。

---

## 三、公众号接入（wewe-rss，需一次性登录）

wewe-rss 通过**微信读书**读取公众号文章，必须有登录态；登录态存在 SQLite 数据库里，提交到仓库后 Actions 每次复用。

**一次性操作（本地有 Docker 即可）：**

```bash
mkdir -p ~/wewe-rss && cd ~/wewe-rss && mkdir -p data
docker run -d --name wewe-local -p 4000:4000 \
  -e DATABASE_TYPE=sqlite \
  -e AUTH_CODE=自己设一个授权码 \
  -e SERVER_ORIGIN_URL=http://localhost:4000 \
  -v "$PWD/data:/app/data" \
  cooderl/wewe-rss-sqlite:latest
```

浏览器打开 `http://localhost:4000`：
1. **微信读书扫码登录**
2. 「公众号管理」里搜索并**添加要订阅的公众号**
3. 等它抓一轮（或手动点更新）

完成后把登录态推进仓库 —— ⚠️ **该库内含「微信读书」登录 cookie，属敏感数据，绝不直接提交**，必须加密后入库：

```bash
cd <本仓库>
mkdir -p data
# 1) 加密（用项目里现成的脚本，会交互式提示输入口令，口令不落盘）
bash <(curl -fsSL https://gitee.com/<你的Gitee用户名>/wanxiang-feeds/raw/master/scripts/encrypt-db.sh) ~/wewe-rss/data/wewe-rss.db
#    或手动：openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
#             -in ~/wewe-rss/data/wewe-rss.db -out data/wewe-rss.db.enc
# 2) 只提交加密文件（明文 *.db 已被 .gitignore 挡住）
git add data/wewe-rss.db.enc
git commit -m "add: wewe-rss 登录态（加密）"
git push
```

> 口令要求：12 位以上，**建议纯字母数字**（中文输入法下全角符号易导致解密失败）。这个口令同时要配到 GitHub Secret `WEWE_DB_PASS`。

再启用该 Job —— GitHub 仓库 **Settings → Secrets and variables → Actions**：
- **Variables** 页新增 `ENABLE_WEWE` = `true`
- **Secrets** 页新增 `WEWE_AUTH_CODE` = 上面设的授权码
- **Secrets** 页新增 `WEWE_DB_PASS` = 加密登录态时输入的那个口令

**⚠️ 登录态会过期**（数周到数月）。表现：「公众号订阅」Job 日志出现「条目为空」。处理：本地按上面步骤重新扫码，**重新加密**并覆盖提交：

```bash
openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
  -in ~/wewe-rss/data/wewe-rss.db -out data/wewe-rss.db.enc   # 用同一个口令
git add data/wewe-rss.db.enc && git commit -m "update: 刷新登录态" && git push
```

> 若换了口令，记得同步更新 GitHub Secret `WEWE_DB_PASS`，否则 Actions 解密失败。

## 三之二、隐私与凭据自检（推送前必做）

仓库公开，推送前跑一遍门禁脚本，确认没有把凭据/个人信息带上去：

```bash
python3 scripts/scan-secrets.py --selftest                  # 先自检，必须全绿
python3 scripts/scan-secrets.py . --tracked                 # 只报已被 git 跟踪的命中
```

命中且被跟踪 → 退出码 1，必须处理。`.gitignore` 已挡住：`.env`、`*.pem/*.key/*.p12`、
`data/*.db`（明文登录态）、依赖与构建产物。

**本仓库刻意不含**：任何账号口令、API 令牌、cookie、本机绝对路径、邮箱、真实手机号。
唯一与个人相关的信息是**你的公众号订阅列表**（在 `feeds/wx-all.json` 里，只含公众号名称与文章），
不含微信账号、阅读记录等任何账号级数据。

---

## 四、万象 App 端接入

产物地址：
```
GitHub:  https://raw.githubusercontent.com/<用户>/wanxiang-feeds/main/feeds/zhihu.json
Gitee :  https://gitee.com/<用户>/wanxiang-feeds/raw/master/feeds/zhihu.json
```

在万象工程的 `sources.json` 里加频道与源（**App 代码无需改动** —— 取数逻辑是「实例 + 路由 + `?format=json`」，多余查询串无害）：

```json
{
  "instances": [
    "https://gitee.com/<你的Gitee用户名>/wanxiang-feeds/raw/master/feeds",
    "https://ghproxy.net/https://raw.githubusercontent.com/<你的Gitee用户名>/wanxiang-feeds/main/feeds",
    "https://rsshub.ktachibana.party",
    "https://rsshub.woodland.cafe"
  ],
  "channels": [
    { "key": "hot", "name": "热榜" },
    { "key": "wx",  "name": "公众号" }
  ],
  "sources": [
    { "id": "hot-zhihu",    "name": "知乎热榜",      "channel": "hot", "route": "/zhihu.json",    "enabled": true },
    { "id": "hot-weibo",    "name": "微博热搜",      "channel": "hot", "route": "/weibo.json",    "enabled": true },
    { "id": "hot-bilibili", "name": "哔哩哔哩热榜",   "channel": "hot", "route": "/bilibili.json", "enabled": true },
    { "id": "hot-toutiao",  "name": "今日头条热榜",   "channel": "hot", "route": "/toutiao.json",  "enabled": true },
    { "id": "hot-36kr",     "name": "36氪热榜",      "channel": "hot", "route": "/36kr.json",     "enabled": true },
    { "id": "hot-ithome",   "name": "IT之家热榜",     "channel": "hot", "route": "/ithome.json",   "enabled": true },
    { "id": "hot-sspai",    "name": "少数派热门",     "channel": "hot", "route": "/sspai.json",    "enabled": true },
    { "id": "hot-github",   "name": "GitHub Trending","channel": "hot","route": "/github.json",   "enabled": true },
    { "id": "wx-all",       "name": "微信公众号",     "channel": "wx",  "route": "/wx-all.json",   "enabled": true }
  ]
}
```

> ⚠️ 上面 `instances` 里两条自定义通道要放在 RSSHub 实例**之前** —— 万象单次最多试 2 个实例，前两位必须可用。

---

## 五、常见问题

**Q：热榜条目点进去为什么要跳浏览器？**
热榜本质是**链接列表**（知乎热榜就是"哪个问题在热"），平台不提供正文。要"点开即读全文"，用**公众号频道**（wewe-rss 全文输出）。两者定位不同：热榜=知道大家在讨论什么，公众号=深度阅读。

**Q：Actions 报「服务未起来」？**
看日志里的 `/tmp/dha.log`。多半是 npm 安装超时，重跑一次即可。

**Q：公众号条目为空？**
登录态过期了，重新登录并更新 `data/wewe-rss.db`（见第三节）。

**Q：仓库公开会不会泄露隐私？**
仓库里只有公开热榜数据 + 你的公众号**订阅列表**（不含阅读记录、不含微信个人信息）。如介意，把公众号部分改为不上云（只在本地跑 wewe-rss），热榜照常。
