# CSMaP Social Archive Python 数据接口

这个模块直接调用 CSMaP 官方 REST API，提供帖子、评论、关键词搜索、用户和社区汇总，以及 CSV/NDJSON 全量导出。运行时只需要 Python 3.10 或更高版本，没有第三方依赖。

接口路径来自 [官方 CLI 源码](https://csmap-social-archive.apps.cloud.rt.nyu.edu/csmap)，仍使用 `/api/v1/...`。本版根据 v2 更新文档和 API key 设置文档增加个人密钥认证，并于 2026-10-06 使用本地密钥文件核对小范围查询和导出。不带密钥的 `/api/v1/stats` 已返回 HTTP 401；下文标明的 2026-10-02 结果属于旧版验证记录。

## 1. 安装与运行

在 PowerShell 中进入研究仓库根目录并安装接口模块：

```powershell
cd D:\Capstone27
python -m pip install -e ./data_interface
```

直接在 `data_interface/` 目录中启动 Python 或运行 `python -m examples.research_export` 时，也可以使用本地包，无须先安装。从研究仓库根目录、Notebook 或其他项目中使用时，建议先执行上述安装命令，并确保它们使用同一个 Python 环境。导入名称仍为 `csmap_client`。

### 填写本地 API Key

在 `data_interface/api_key.txt` 中填写个人 CSMaP API key，只保留一行密钥，不加引号、不加 `Bearer`，也不写 `CSMAP_API_KEY=`。将文件中的 `PASTE_YOUR_CSMAP_API_KEY_HERE` 完全替换。密钥在 CSMaP 网页的 API access 中创建。

首次克隆仓库时，真实密钥文件不会随 Git 下载。可以在研究仓库根目录运行以下命令，仅在文件不存在时从模板创建：

```powershell
if (-not (Test-Path ./data_interface/api_key.txt)) {
    Copy-Item ./data_interface/api_key.example.txt ./data_interface/api_key.txt
}
```

`api_key.txt` 已加入 `.gitignore`，`api_key.example.txt` 仅包含占位符。不要把真实密钥写进模板、研究脚本、Notebook、README 或提交记录，也不要用 `git add -f` 强制提交密钥文件。密钥被撤销或替换后，需要更新本地文件，并重新创建客户端。

## 2. 创建客户端

```python
from csmap_client import CsmapClient

client = CsmapClient(timeout=120, max_retries=2)
print(client.stats())
```

默认地址为 `https://csmap-social-archive.apps.cloud.rt.nyu.edu`。新版直接 API 调用需要个人 API key，客户端自动发送 `Authorization: Bearer <key>`，不需要在 Python 中执行网页登录。

在本仓库源码或 editable 安装模式下，默认文件位于 `data_interface/api_key.txt`，由客户端源码位置定位，不受研究脚本、Notebook 或终端当前工作目录影响。缺少密钥或仍使用占位符时，客户端在发起请求前报错。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `base_url` | 官方地址，或环境变量 `CSMAP_URL` | 服务根地址；不要加 `/api/v1` |
| `api_key` | `None` | 显式传入密钥；不要在代码中硬编码真实密钥 |
| `api_key_file` | `None` | 显式指定 UTF-8 密钥文件路径，支持 `pathlib.Path`；相对路径相对于当前工作目录 |
| `timeout` | `120` | 每次连接和读取的超时秒数，不是整个大文件下载的总时长上限 |
| `max_retries` | `2` | 首次请求失败后的额外尝试次数，最多请求 3 次 |
| `backoff` | `0.5` | 本地指数退避基础秒数，本地退避上限 30 秒；服务端 `Retry-After` 要求的等待时间不受此上限限制 |
| `headers` | `None` | 额外 HTTP 请求头；已有 `Authorization` 时保留该值，不与显式 `api_key` / `api_key_file` 混用 |

密钥优先级为：显式 `api_key` > 显式 `api_key_file` > 环境变量 `CSMAP_API_KEY` > 默认 `api_key.txt`。显式文件无效时不会悄悄退回其他来源；如果设置了环境变量，它会覆盖默认文件。手动传入 `Authorization` 请求头属于兼容模式，会跳过自动密钥加载。

显式读取其他位置的文件：

```python
from pathlib import Path

client = CsmapClient(api_key_file=Path("D:/Capstone27/data_interface/api_key.txt"))
```

使用 wheel 安装到其他环境时，请通过 `api_key_file` 指定自己的文件位置，或设置 `CSMAP_API_KEY`；wheel 不携带本地密钥文件。仅将密钥发送到可信 HTTPS 服务，不把自定义 `base_url` 指向未知地址。

可显式切换服务：

```python
client = CsmapClient(base_url="https://csmap-social-archive.apps.cloud.rt.nyu.edu")
```

## 3. 查询一页帖子或评论

```python
page = client.posts(
    subreddit=["science", "politics"],
    after="2024-01-01",
    before="2024-01-31",
    min_score=100,
    sort="score",
    order="desc",
    limit=25,
    page=1,
)

for post in page.items:
    print(post["id"], post["title"], post["score"])

print(page.total, page.total_pages, page.has_more)

comments = client.comments(
    subreddit="science",
    author="mvea",
    after="2024-01-01",
    before="2024-01-31",
    limit=25,
)
for comment in comments.items:
    print(comment["post_id"], comment["body"])
```

列表方法返回 `Page`，一条 `page.items` 元素是一个 Python `dict`。字段名称与值保留服务端内容，不补造缺失字段，也不将字符串 ID 转成数字。

| `Page` 属性 | 含义 |
|---|---|
| `items` | 本页的记录列表：`list[dict]` |
| `page` / `limit` | 当前页码、服务端返回的每页大小 |
| `total` / `total_pages` | 匹配数量、总页数；服务端没有提供时为 `None` |
| `has_more` | 是否还有下一页 |
| `raw` | 未改写结构的完整 JSON 响应，保留 `meta`、`links` 等信息 |

普通列表返回 `{"data": [...], "meta": {...}, "links": {...}}`，搜索返回 `{"results": [...], "page": 1, "limit": 25, "has_more": true}`，月度汇总返回 `{"data": [...], "meta": {"frequency": "month", ...}}`。v2 文档新增网页搜索结果总数和总页数，但 2026-10-06 带密钥的 `/api/v1/search` 实测仍只有 `results`、`page`、`limit`、`has_more`，没有总数，因此 `Page.total` / `total_pages` 为 `None`。如果服务器后续增加顶层或 `meta` 内的 `total` / `total_pages`，客户端已经支持读取，不会在本地估算。

## 4. 共享筛选条件

| 参数 | 可用值与规则 |
|---|---|
| `subreddit` | 一个名称、逗号分隔字符串或名称列表，如 `"science,politics"`；支持去除 `r/` 前缀 |
| `author` | 一个用户名、逗号分隔字符串或用户名列表；支持去除 `u/` 前缀 |
| `after` / `before` | `YYYY-MM-DD` 字符串或 `datetime.date`；起始日期不能晚于结束日期 |
| `min_score` | 整数，可为 `0` 或负数；`None` 表示不筛选 |
| `sort` | `"date"`、`"score"` 或 `"comments"`；评论查询不接受 `"comments"` |
| `order` | `"desc"` 或 `"asc"`，默认 `"desc"` |
| `limit` | 每页 10 到 200 条，默认 25；实测服务端会将小于 10 的值提升到 10，本客户端直接校验范围 |
| `page` | 从 1 开始，默认 1 |

日期边界、各汇总端点支持的排序或筛选由服务端决定。客户端将参数传给官方 API，不在本地模拟这些规则。可以限定社区、作者或日期范围来缩小查询。

v2 文档明确说明 Subreddits 的 Users 网页视图中 To 日期包含选中整天。2026-10-06 帖子 API 实测也包含 `before` 所指定的整天：science 的 `after="2024-01-15", before="2024-01-16"` 匹配 83 条，最新帖子时间为 `2024-01-16T23:13:34Z`。因此查询完整一月时使用 `before="2024-01-31"`，不要照搬旧版的 `before="2024-02-01"`，否则可能包含二月第一天。其他端点仍应分别验证；客户端不会自动将结束日期加一天。

同一组条件可以复用：

```python
from csmap_client import Filters

scope = Filters(subreddit="science", after="2024-01-01", before="2024-01-31")
posts = client.posts(filters=scope)
comments = client.comments(filters=scope)
second_page = client.posts(filters=scope, page=2, limit=100)
```

显式关键字会覆盖 `Filters` 中同名的值；传入未知参数会抛出 `TypeError`。

## 5. 关键词搜索

```python
page = client.search(
    "climate AND policy",
    type="posts",
    subreddit="science",
    after="2024-01-01",
    before="2024-01-31",
    limit=25,
)
comment_page = client.search("vaccine NOT covid", type="comments", subreddit="science")
alternative_page = client.search("brexit OR referendum", type="posts", subreddit="politics")
```

v2 文档支持 `AND`、`OR`、`NOT`：分别表示同时匹配、匹配任一项、排除某个词。客户端将查询字符串原样编码并发送到服务端，不在本地重新解释语法，也不自行承诺未文档化的引号、括号或优先级规则。

2026-10-06 已在 science 的 2024 年 1 月 REST 搜索中验证布尔行为：`vaccine` 匹配 13 条，`vaccine AND covid` 匹配 6 条，`vaccine NOT covid` 匹配 7 条，AND 与 NOT 结果不重叠且合起来等于原结果；OR 一个未匹配词保留原结果。这些数量只是当次验证记录，不是固定返回值。

`type` 仍支持 `"posts"` 和 `"comments"`。网页的 Posts + Comments 模式不能直接等同于 REST API 接受 `type="both"`；在官方契约确认前，研究脚本应分别查询或导出帖子和评论。Name/Topic 社区发现也暂未新增未经确认的 REST 路径。

## 6. 自动分页

```python
for post in client.iter_posts(filters=scope, limit=100, max_items=500):
    print(post["id"], post["title"])

for comment in client.iter_comments(filters=scope, max_pages=2):
    print(comment["id"], comment["body"])

for item in client.iter_search("climate change", type="posts", filters=scope, max_items=50):
    print(item["id"])
```

迭代器逐页请求、逐条输出，不会一次加载全部数据。`max_pages` 限制读取页数，`max_items` 限制输出条数；两者默认不限制，指定时必须为正整数。`page` 决定从哪一页开始。

客户端依据分页元数据或搜索的 `has_more` 决定是否继续，每页重新携带原筛选条件。已观察到服务端 `links.next` 不包含原筛选参数，因此客户端不直接跟随该链接。若服务端重复上一页或返回矛盾的分页信息，客户端抛出 `ResponseError`。跨多次请求没有快照保证；大批量离线分析建议使用下一节的服务端全量导出。

v2 文档将网页浏览限制为前 10,000 条结果，默认每页 25 条时为 400 页。REST API 是否施加相同限制、如何返回限额元数据仍待验证，因此客户端不硬编码 400 页，也不把 `iter_search()` 承诺为不受限制的全量获取方法。明确的 `has_more=False` 优先于总数决定停止；需要全部匹配记录时使用服务端导出。

## 7. CSV / NDJSON 全量导出

```python
path = client.export_posts("data/science_posts.ndjson", filters=scope)
client.export_comments("data/science_comments.csv", filters=scope)
client.export_search(
    "climate change",
    "data/climate_posts.ndjson",
    type="posts",
    filters=scope,
    min_score=100,
)
print(path)
```

这些方法下载所有符合条件的记录。即使 `Filters` 中设置了 `page` 或 `limit`，导出时也不会发送这两个分页参数。

格式默认根据 `.csv`、`.ndjson` 或 `.jsonl` 扩展名推断，也可指定 `format="csv"` 或 `format="ndjson"`。返回值是文件的绝对 `pathlib.Path`。父目录自动创建；目标文件已存在时默认抛出 `FileExistsError`，明确传入 `overwrite=True` 才替换。

下载以 64 KiB 数据块写入同目录临时文件，完整成功后才提交目标文件。下载中断会清理临时文件并保留原目标文件，不自动续传。默认的无覆盖提交使用同目录硬链接，需要文件系统支持硬链接；当前 Windows NTFS 工作目录可用。

`export()` 还支持官方 CLI 标明可服务端导出的用户帖子、用户评论和社区作者：

```python
client.export("user_posts", "data/mvea_posts.ndjson", name="mvea", filters=scope)
client.export("user_comments", "data/mvea_comments.csv", name="mvea", filters=scope)
client.export("subreddit_users", "data/science_users.csv", name="science", filters=scope)
```

普通帖子 JSON 与导出记录字段不完全相同：导出增加 `selftext` 和 `domain`；实测帖子导出有 `created_at`，普通查询还包含数字时间戳 `created_utc`。研究正文时建议导出，不假定两种方式有完全一致的字段。

v2 文档增加下载列 `reddit_url`，用于打开原始 Reddit 页面。客户端不筛选或重新序列化下载字段，直接保存服务器返回的 CSV/NDJSON，因此不会丢掉新增列。网页中的 Net votes 是原 Score 的显示名称；Python 仍使用 `score` / `min_score`，不自行改名。非常大的下载建议使用 NDJSON。

CSV 为 UTF-8，实测官方 CSV 包含 BOM，可使用 `utf-8-sig` 读取；NDJSON 每行是一个独立 JSON 对象：

```python
import csv
import json

with open("data/science_comments.csv", encoding="utf-8-sig", newline="") as stream:
    for row in csv.DictReader(stream):
        print(row["id"], row["body"])

with open("data/science_posts.ndjson", encoding="utf-8") as stream:
    for line in stream:
        post = json.loads(line)
        print(post["id"], post.get("selftext", ""))
```

## 8. 所有查询接口

除 `stats()`、`raw()` 外，以下方法均返回 `Page`。除 `subreddits()` 只接受 `limit`、`page` 外，列表方法支持 `filters=Filters(...)` 或共享筛选关键字。

| Python 调用 | HTTP 路径 | 返回内容 |
|---|---|---|
| `client.stats()` | `/api/v1/stats` | 档案总量，返回 `dict` |
| `client.posts(...)` | `/api/v1/posts` | 帖子 |
| `client.comments(...)` | `/api/v1/comments` | 评论 |
| `client.search("关键词", type="posts", ...)` | `/api/v1/search` | 匹配帖子或评论 |
| `client.user_posts("mvea", ...)` | `/api/v1/users/mvea/posts` | 指定作者的帖子 |
| `client.user_comments("mvea", ...)` | `/api/v1/users/mvea/comments` | 指定作者的评论 |
| `client.user_communities("mvea", ...)` | `/api/v1/users/mvea/communities` | 作者参与的社区 |
| `client.user_timeseries("mvea", ...)` | `/api/v1/users/mvea/timeseries` | 作者月度活动 |
| `client.subreddit_users("science", ...)` | `/api/v1/subreddits/science/users` | 社区作者统计 |
| `client.subreddit_timeseries("science", ...)` | `/api/v1/subreddits/science/timeseries` | 社区月度活动 |
| `client.subreddits(limit=25, page=1)` | `/api/v1/subreddits/top` | 社区活跃度列表 |
| `client.raw("/api/v1/stats", params={...})` | 指定的 `/api/v1/...` 路径 | 原始解码 JSON，可为对象或列表 |

`user_*` 与 `subreddit_*` 的位置参数 `name` 只接受一个用户名或社区名，可带 `u/` 或 `r/` 前缀。查询多个社区的帖子、评论时，使用 `posts/comments/search` 的 `subreddit` 筛选。

```python
communities = client.user_communities("mvea", after="2024-01-01", before="2024-01-31")
activity = client.user_timeseries("mvea", after="2024-01-01", before="2024-01-31")
authors = client.subreddit_users("science", after="2024-01-01", before="2024-01-31")
top = client.subreddits(limit=10)
original = client.raw("/api/v1/subreddits/science/users", params={"limit": 10})
```

汇总接口中的一条 item 可能是一个作者、一个社区或一个月份。使用 `Page.items` 获取记录；若要保存非服务端导出的汇总视图，可以保存已经获取的结果，不把一页误当作全量：

```python
with open("mvea_activity.json", "w", encoding="utf-8") as stream:
    json.dump(activity.raw, stream, ensure_ascii=False, indent=2)
```

`raw()` 是直接调用 API，不是取得数据字典中的 `json_data`。完整原始 Reddit 对象目前没有通过 API/CLI 开放；`parent_id`、`depth`、flair、awards 等字段也不应预设一定可取得。

## 9. 异常与当前服务限制

```python
from csmap_client import ApiError, AuthenticationError, NetworkError, ResponseError

try:
    activity = client.subreddit_timeseries("science", after="2024-01-01", before="2024-01-31")
except AuthenticationError as error:
    print("Access rejected:", error.status_code)
except ApiError as error:
    print("API error:", error.status_code, error.path, error.message)
except NetworkError as error:
    print("Connection or download failed:", error)
except ResponseError as error:
    print("Unexpected response:", error)
```

HTTP 429、500、502、503、504 与连接/超时错误会在建立请求时按配置重试；401/403 不重试。收到 JSON 后的解析错误、流式下载中的读取失败不会自动重试。参数错误使用 `ValueError` 或 `TypeError`；文件操作错误使用相应的 `OSError` 子类。

密钥缺失、空白或仍为占位符时，在构造客户端时抛出 `ValueError`；显式文件不存在时抛出 `FileNotFoundError`。被撤销或无效的密钥由服务端返回 401/403，抛出 `AuthenticationError`。错误信息不会回显客户端使用的 Bearer 密钥。

新版按个人密钥限制使用量，下载也记录在该密钥所属用户下。客户端同时支持 `Retry-After` 的秒数和 HTTP 日期格式；服务器要求等待超过 30 秒时会遵守，重试次数仍由 `max_retries` 限制。文档没有明确额度，不预设每分钟请求数；重试耗尽后保留 HTTP 429 错误，不把限流当作空数据。

历史记录：2026-10-02 的 `subreddit_timeseries("science", after="2024-01-01", before="2024-02-01")` 曾返回 HTTP 500。2026-10-06 带密钥复测同一查询已成功，返回 2 条月度记录，字段为 `subreddit`、`period`、`post_count`、`comment_count`、`unique_authors`、`avg_score`。这不是所有时间范围的可用性保证；服务端再次失败时仍保留错误，不伪装成空结果。

## 10. 命令行研究导出示例

以下示例导出 science 社区指定日期范围内匹配 climate change 的全部帖子：

先按第 1 节填写 `data_interface/api_key.txt`，示例会自动读取；也可用 `--api-key-file` 指定其他文件。

```powershell
cd D:\Capstone27\data_interface
python -m examples.research_export --subreddit science --after 2024-01-01 --before 2024-01-31 --keywords "climate change" --type posts --output data/climate.ndjson
```

去掉 `--keywords` 可以导出筛选后的所有帖子；`--type comments` 改为评论；输出扩展名改为 `.csv` 可导出 CSV。另支持 `--author`、`--min-score`、`--url`、`--api-key-file`、`--timeout`、`--overwrite`。缺少密钥或密钥文件不可读时，示例显示错误并退出，不输出密钥。

## 11. 验证

以下测试命令在 `data_interface/` 目录执行。离线测试使用模拟 HTTP 响应，不依赖官方服务：

```powershell
python -m unittest discover -s tests -v
```

可选的在线集成测试需要先填写密钥文件或设置 `CSMAP_API_KEY`，会消耗个人 API 使用量，并将小范围导出写入自动清理的临时目录：

```powershell
$env:CSMAP_LIVE_TESTS = "1"
python -m unittest discover -s tests -p test_live.py -v
Remove-Item Env:\CSMAP_LIVE_TESTS
```

在线测试包括帖子和评论、搜索、用户和社区汇总、全量导出，以及帖子结束日期包含当天的检查。搜索测试接受有总数或无总数的响应，不固定断言 `total is None`。测试失败时，应查看错误状态与服务当前可用性。

0.2.0 于 2026-10-06 通过 43 项离线测试与 9 项带密钥在线测试，在线验证包含布尔查询结果集合、结束日期、社区月度汇总和带 `reddit_url` 的 CSV 下载。离线测试同时在项目的 Python 3.10 和内置运行环境通过。

历史版本于 2026-10-02 通过 24 项离线测试与 7 项在线集成测试。science 社区 2024-01-15 至 2024-01-16 的帖子查询返回总数 35；CSV 与 NDJSON 导出均取得 35 条记录。这些不是新版带密钥验证结果。新版离线测试增加文件认证、凭据优先级、密钥脱敏、搜索总数、布尔表达式原样传递、导出新列和限流等待检查。

0.2.0 的 wheel 已构建，并通过临时安装和显式密钥文件读取检查；压缩包中包含 `auth.py`，不包含 `api_key.txt`。离线测试不使用真实密钥，不消耗 API 使用量。

接口包版本为 `0.2.0`。从 `data_interface/` 执行 `python -m pip wheel . --no-deps -w dist` 可构建 wheel；本地密钥文件不包含在 wheel 中。向其他 Python 环境安装时仍需配置自己的密钥。

## 12. 文件结构

```text
data_interface/
  README.md
  pyproject.toml
  api_key.example.txt Template only, no real key
  api_key.txt         Local secret, ignored by Git
  csmap_client/
    __init__.py       Public imports
    client.py         Query methods, pagination, exports
    auth.py           Credential loading and header validation
    models.py         Filters and Page
    transport.py      HTTP requests, retries, atomic streaming
    errors.py         Public exception classes
  examples/
    research_export.py
  tests/
    test_client.py
    test_auth.py
    test_live.py
```
