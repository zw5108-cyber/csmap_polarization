# CSMaP Polarization Research

本仓库用于研究项目。CSMaP 数据获取接口作为独立模块维护，相关源码、说明、示例、测试和打包配置集中在 `data_interface/` 中。

## 当前结构

```text
data_interface/
  README.md          接口调用说明
  pyproject.toml     接口模块的 Python 打包配置
  csmap_client/      Python 客户端源码
  examples/          数据导出示例
  tests/             离线测试和可选在线集成测试
```

## 使用数据接口

在研究仓库根目录安装接口模块：

```powershell
python -m pip install -e ./data_interface
```

安装后，研究脚本或 Notebook 可以直接导入：

```python
from csmap_client import CsmapClient, Filters
```

查询、分页、CSV/NDJSON 导出及异常处理详见 [接口调用说明](data_interface/README.md)。运行导出示例时，先进入 `data_interface/` 目录。

## 验证接口

安装模块后，可以从研究仓库根目录执行离线测试：

```powershell
python -m unittest discover -s data_interface/tests -p test_client.py -v
```
