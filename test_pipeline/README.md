# Flowcontainer Pipeline 测试

这个目录包含用于测试 Flowcontainer 镜像集成的 Snakemake 工作流。

## 📁 文件结构

```
test_pipeline/
├── Snakefile          # 测试工作流
└── README.md          # 本文档
```

## 🚀 快速开始

### 1. 查看可用镜像

```bash
cd test_pipeline
snakemake -c 1 list_available_images
```

这会读取 `../container_env.yaml` 并列出所有可用镜像。

### 2. 本地运行测试（不使用容器）

```bash
# 运行所有测试
snakemake -c 1

# 或运行特定测试
snakemake -c 1 test_rsem_container
snakemake -c 1 test_samtools_container
```

### 3. 使用容器运行测试（推荐）

```bash
# 需要安装 singularity 或 apptainer
snakemake -c 1 --use-singularity
```

## 📋 测试规则说明

| 规则名 | 说明 | 使用的镜像 |
|--------|------|-----------|
| `test_rsem_container` | 测试 RSEM 容器 | `rnaflow-rsem` |
| `test_samtools_container` | 测试 Samtools（自动查找） | 根据工具名自动查找 |
| `multi_tool_in_one_container` | 同一容器中多工具测试 | `rnaflow-rsem` |
| `dynamic_image_selection` | 动态选择镜像 | 根据配置选择 |
| `list_available_images` | 列出可用镜像 | 无（纯 Python） |

## 🔧 关键功能展示

### 1. 读取 container_env.yaml

```python
import yaml

# 自动加载配置
with open("../container_env.yaml") as f:
    config = yaml.safe_load(f)

IMAGES = config.get("images", {})
```

### 2. 使用特定镜像

```python
def get_image(name):
    uri = IMAGES[name]["full_image_uri"]
    return f"docker://{uri}"

rule example:
    container:
        get_image("rnaflow-rsem")
    shell:
        "rsem-calculate-expression --version"
```

### 3. 根据工具自动选择镜像

```python
def get_image_by_tool(tool_name):
    for name, info in IMAGES.items():
        if tool_name in info.get("tools", []):
            return f"docker://{info['full_image_uri']}"
    raise ValueError(f"找不到包含工具 '{tool_name}' 的镜像")

rule auto_select:
    container:
        get_image_by_tool("samtools")
    shell:
        "samtools --version"
```

## 📝 动态配置

创建 `workflow_config.yaml` 覆盖默认配置：

```yaml
rsem_image: "test-rsem"  # 选择不同的镜像
test_mode: true          # 启用测试模式
```

然后运行：

```bash
snakemake -c 1 dynamic_image_selection --use-singularity
```

## 🔍 查看结果

测试完成后查看结果：

```bash
# 查看测试结果
cat results/rsem_test_completed.txt
cat results/samtools_test_completed.txt
cat results/multi_tool_test.txt

# 查看可用镜像列表
cat results/available_images.txt
```

## 🧹 清理

```bash
snakemake clean
```

## ❓ 常见问题

### Q: 找不到镜像？

检查 `container_env.yaml` 路径是否正确：

```python
CONFIG_FILE = Path("../container_env.yaml")  # 根据实际情况调整
```

### Q: 容器运行失败？

确保已安装 singularity/apptainer：

```bash
# 检查安装
singularity --version
# 或
apptainer --version
```

### Q: 如何添加新镜像测试？

1. 先构建镜像：`flowcontainer build -e envs/xxx.yaml`
2. 修改 Snakefile 添加新 rule
3. 使用 `get_image("新镜像名")` 引用
