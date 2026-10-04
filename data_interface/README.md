# CSMaP Social Archive Python 数据接口

这个模块直接调用 CSMaP 官方 REST API，提供帖子、评论、关键词搜索、用户和社区汇总，以及 CSV/NDJSON 全量导出。运行时只需要 Python 3.10 或更高版本，没有第三方依赖。

接口路径来自 [官方 CLI 源码](https://csmap-social-archive.apps.cloud.rt.nyu.edu/csmap)。以下响应结构与可用性于 2026-10-02 使用少量公开读取请求核对。

## 1. 安装与运行

在 PowerShell 中进入研究仓库根目录并安装接口模块：

```powershell
cd D:\Capstone27
python -m pip install -e ./data_interface
```

直接在 `data_interface/` 目录中启动 Python 或运行 `python -m examples.research_export` 时，也可以使用本地包，无须先安装。从研究仓库根目录、Notebook 或其他项目中使用时，建议先执行上述安装命令，并确保它们使用同一个 Python 环境。导入名称仍为 `csmap_client`。

## 2. 创建客户端

```python
from csmap_client import CsmapClient

client = CsmapClient(timeout=120, max_retries=2)
print(client.stats())
```

默认地址为 `https://csmap-social-archive.apps.cloud.rt.nyu.edu`。官方 CLI 明确说明，当前公开读取端点不需要登录；网页的 NYU 登录要求不应直接套用到这些公开 API。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `base_url` | 官方地址，或环境变量 `CSMAP_URL` | 服务根地址；不要加 `/api/v1` |
| `timeout` | `120` | 每次连接和读取的超时秒数，不是整个大文件下载的总时长上限 |
| `max_retries` | `2` | 首次请求失败后的额外尝试次数，最多请求 3 次 |
| `backoff` | `0.5` | 重试退避的基础秒数；单次等待最多 30 秒 |
| `headers` | `None` | 额外 HTTP 请求头，用于自定义部署等场景 |

可显式切换服务：

```python
client = CsmapClient(base_url="https://csmap-social-archive.apps.cloud.rt.nyu.edu")
```

## 3. 查询一页帖子或评论

```python
page = client.posts(
    subreddit=["science", "politics"],
    after="2024-01-01",
    before="2024-02-01",
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
    before="2024-02-01",
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

普通列表实际返回 `{"data": [...], "meta": {...}, "links": {...}}`；搜索实际返回 `{"results": [...], "page": 1, "limit": 25, "has_more": true}`，没有总数；用户月度汇总实际返回 `{"data": [...], "meta": {"frequency": "month", ...}}`，没有分页信息。客户端统一这些结构，但不会编造搜索总数。

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

日期边界是否包含当天、各汇总端点是否支持某个排序或筛选，由服务端决定。客户端将参数传给官方 API，不在本地模拟这些规则。可以限定社区、作者或日期范围来缩小查询。

同一组条件可以复用：

```python
from csmap_client import Filters

scope = Filters(subreddit="science", after="2024-01-01", before="2024-02-01")
posts = client.posts(filters=scope)
comments = client.comments(filters=scope)
second_page = client.posts(filters=scope, page=2, limit=100)
```

显式关键字会覆盖 `Filters` 中同名的值；传入未知参数会抛出 `TypeError`。

## 5. 关键词搜索

```python
page = client.search(
    "climate change, tesla",
    type="posts",
    subreddit="science",
    after="2024-01-01",
    before="2024-02-01",
    limit=25,
)
comment_page = client.search("climate change", type="comments", subreddit="science")
```

`type` 支持 `"posts"` 和 `"comments"`。逗号分隔的主题之间为 OR，同一主题中的词为 AND。`climate change, tesla` 表示同时包含 climate 与 change，或者包含 tesla；不要求 climate 与 change 相邻。根据文档，匹配忽略大小写和标点，按完整单词匹配，不支持引号、减号等特殊查询操作符。要同时研究帖子和评论，请分别调用两次。

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
communities = client.user_communities("mvea", after="2024-01-01", before="2024-02-01")
activity = client.user_timeseries("mvea", after="2024-01-01", before="2024-02-01")
authors = client.subreddit_users("science", after="2024-01-01", before="2024-02-01")
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
    activity = client.subreddit_timeseries("science", after="2024-01-01", before="2024-02-01")
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

2026-10-02 实测 `subreddit_timeseries("science", after="2024-01-01", before="2024-02-01")` 返回 HTTP 500。该方法已实现正确路径与参数并保留错误信息，但此查询需要服务端修复才能成功；客户端没有将它伪装成空结果。用户月度汇总、社区作者、普通列表和搜索的对应小范围查询已成功。

## 10. 命令行研究导出示例

以下示例导出 science 社区指定日期范围内匹配 climate change 的全部帖子：

```powershell
cd D:\Capstone27\data_interface
python -m examples.research_export --subreddit science --after 2024-01-01 --before 2024-02-01 --keywords "climate change" --type posts --output data/climate.ndjson
```

去掉 `--keywords` 可以导出筛选后的所有帖子；`--type comments` 改为评论；输出扩展名改为 `.csv` 可导出 CSV。另支持 `--author`、`--min-score`、`--url`、`--timeout`、`--overwrite`。

## 11. 验证

以下测试命令在 `data_interface/` 目录执行。离线测试使用模拟 HTTP 响应，不依赖官方服务：

```powershell
python -m unittest discover -s tests -v
```

可选的在线集成测试会请求官方公开 API，并将小范围导出写入自动清理的临时目录：

```powershell
$env:CSMAP_LIVE_TESTS = "1"
python -m unittest discover -s tests -p test_live.py -v
Remove-Item Env:\CSMAP_LIVE_TESTS
```

在线测试不把已观察到返回 500 的社区月度汇总当作健康接口。其他测试失败时，应查看错误状态与服务当前可用性。

本版本于 2026-10-02 通过 24 项离线测试与 7 项在线集成测试。science 社区 2024-01-15 至 2024-01-16 的帖子查询返回总数 35；CSV 与 NDJSON 导出均取得 35 条记录，验证了全量导出语义。

安装包构建也已通过，生成 `data_interface/dist/csmap_client-0.1.0-py3-none-any.whl`。从研究仓库根目录可执行 `python -m pip install data_interface/dist/csmap_client-0.1.0-py3-none-any.whl`，将安装包安装到其他 Python 环境。

## 12. 文件结构

```text
data_interface/
  README.md
  pyproject.toml
  csmap_client/
    __init__.py       Public imports
    client.py         Query methods, pagination, exports
    models.py         Filters and Page
    transport.py      HTTP requests, retries, atomic streaming
    errors.py         Public exception classes
  examples/
    research_export.py
  tests/
    test_client.py
    test_live.py
```
