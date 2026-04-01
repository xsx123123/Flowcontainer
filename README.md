# Flowcontainer 🐳

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://docs.docker.com/get-docker/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Flowcontainer** - 生物信息学工作流容器镜像构建工具，基于 Conda 环境自动生成 Docker 镜像。

```
  ███████╗██╗      ██████╗ ██╗    ██╗   ██╗██╗
  ██╔════╝██║     ██╔═══██╗██║    ██║   ██║██║
  █████╗  ██║     ██║   ██║██║    ██║   ██║██║
  ██╔══╝  ██║     ██║   ██║██║    ██║   ██║██║
  ██║     ███████╗╚██████╔╝██║    ╚██████╔╝██║
  ╚═╝     ╚══════╝ ╚═════╝ ╚═╝     ╚═════╝ ╚═╝
           Container Image Builder
```

## ✨ 特性

- 🐳 **Docker SDK 集成** - 使用官方 Python SDK，替代 subprocess 调用
- 🔧 **配置文件管理** - 支持 `Flowcontainer.yaml` 集中管理配置
- 🌐 **Registry 检查** - 自动检测 Registry 连通性，避免推送失败
- 📦 **批量构建** - 一键构建目录中所有 Conda 环境
- 🧪 **镜像测试** - 自动验证镜像内工具可用性
- 📝 **环境记录** - 自动生成 `container_env.yaml` 供后续使用
- 🎨 **Rich 美化** - 彩色终端输出，emoji 点缀
- 🚀 **无 pycache** - 自动设置不生成 `__pycache__`

---

## 📦 安装

### 环境要求

- Python 3.8+
- Docker (必需)
- pip

### 方式一：开发模式安装（推荐）

适用于需要修改代码或查看源码的场景：

```bash
cd /home/zj/pipeline/RNAFlow/container_env
pip install -e .
```

`-e` 表示 editable（可编辑模式），修改代码后无需重新安装。

### 方式二：普通安装

```bash
cd /home/zj/pipeline/RNAFlow/container_env
pip install .
```

### 方式三：作为 Python 模块运行（无需安装）

```bash
cd /home/zj/pipeline/RNAFlow/container_env
python -m Flowcontainer --version
```

### 验证安装

```bash
# 查看版本
flowcontainer --version

# 显示帮助
flowcontainer --help
```

---

## 🚀 快速开始

### 第一步：初始化配置（可选但推荐）

```bash
# 创建默认配置文件 Flowcontainer.yaml
flowcontainer init
```

这会生成一个 `Flowcontainer.yaml` 文件，你可以编辑它来设置默认值：

```yaml
version: "1.0.0"

build:
  default_registry: "registry.example.com/"
  default_tag_prefix: "rnaflow"
  default_version: "0.1.0"

registry:
  url: "registry.example.com"
  insecure: false
```

### 第二步：检查环境

```bash
# 检查 Docker 和 Registry 连通性
flowcontainer doctor
```

### 第三步：构建镜像

```bash
# 构建单个环境
flowcontainer build -e ../envs/rsem.yaml -t rnaflow-rsem:0.1

# 构建并指定测试工具
flowcontainer build -e ../envs/rsem.yaml -t rnaflow-rsem:0.1 \
  --test-tools "rsem-calculate-expression"

# 构建并推送
flowcontainer build -e ../envs/rsem.yaml --push --registry registry.io/

# 批量构建整个目录
flowcontainer batch ../envs/ --push
```

---

## 📋 命令详解

### `flowcontainer build` - 构建单个镜像

构建单个 Conda 环境为 Docker 镜像。

```bash
flowcontainer build -e <env-file> [options]
```

**参数说明：**

| 参数 | 说明 | 示例 |
|------|------|------|
| `-e, --env` | Conda 环境 yaml 文件路径（必需） | `-e envs/rsem.yaml` |
| `-t, --tag` | 镜像标签 | `-t rnaflow-rsem:0.1` |
| `-r, --registry` | 镜像仓库地址 | `-r registry.io/` |
| `--push` | 构建后推送镜像 | `--push` |
| `--no-cache` | 不使用 Docker 缓存 | `--no-cache` |
| `--health-check` | 自定义健康检查命令 | `--health-check 'rsem --version'` |
| `--test-tools` | 指定要测试的工具 | `--test-tools 'rsem' 'samtools'` |
| `--output-yaml` | 输出容器环境配置 | `--output-yaml container_env.yaml` |
| `--no-logo` | 不显示 Logo | `--no-logo` |

**示例：**

```bash
# 基础构建
flowcontainer build -e envs/bwa2.yaml -t bwa-mem2:v1

# 自定义健康检查和测试工具
flowcontainer build -e envs/gatk.yaml \
  -t gatk:4.3.0 \
  --health-check 'gatk --version' \
  --test-tools 'gatk'

# 使用配置文件中的 registry 并推送
flowcontainer build -e envs/fastqc.yaml --push
```

---

### `flowcontainer batch` - 批量构建

批量构建目录中的所有 Conda 环境文件。

```bash
flowcontainer batch <env-dir> [options]
```

**参数说明：**

| 参数 | 说明 | 示例 |
|------|------|------|
| `env_dir` | 包含 .yaml/.yml 环境文件的目录 | `../envs/` |
| `-r, --registry` | 镜像仓库地址 | `-r registry.io/` |
| `--push` | 构建后推送镜像 | `--push` |
| `--output-yaml` | 输出容器环境配置 | `--output-yaml container_env.yaml` |

**示例：**

```bash
# 批量构建（不推送）
flowcontainer batch ../envs/

# 批量构建并推送
flowcontainer batch ../envs/ --push --registry registry.io/
```

---

### `flowcontainer doctor` - 环境检查

检查 Docker 和 Registry 是否配置正确。

```bash
flowcontainer doctor [--registry REGISTRY]
```

**示例：**

```bash
# 检查默认配置
flowcontainer doctor

# 检查指定 Registry
flowcontainer doctor --registry registry.example.com
```

---

### `flowcontainer init` - 初始化配置

创建默认的 `Flowcontainer.yaml` 配置文件。

```bash
flowcontainer init [options]
```

**参数说明：**

| 参数 | 说明 | 示例 |
|------|------|------|
| `-o, --output` | 输出路径 | `-o ~/Flowcontainer.yaml` |

**示例：**

```bash
# 当前目录创建配置
flowcontainer init

# 指定路径创建
flowcontainer init -o ~/.config/flowcontainer/config.yaml
```

---

## ⚙️ 配置文件详解

### 配置文件搜索顺序

Flowcontainer 会按以下顺序查找配置文件（优先级递减）：

1. 当前目录: `./Flowcontainer.yaml`
2. 用户配置: `~/.config/flowcontainer/Flowcontainer.yaml`
3. 系统配置: `/etc/flowcontainer/Flowcontainer.yaml`

### 完整配置示例

```yaml
version: "1.0.0"

# ========== 构建配置 ==========
build:
  # 默认推送仓库地址
  # 示例: registry.example.com/ 或 docker.io/username/
  default_registry: ""
  
  # 默认镜像标签前缀
  default_tag_prefix: "rnaflow"
  
  # 默认版本号
  default_version: "latest"
  
  # 默认是否不使用缓存
  no_cache: false
  
  # 并行构建数 (1表示串行)
  parallel: 1
  
  # 自定义 Dockerfile 模板路径
  template_file: null

# ========== Registry 配置 ==========
registry:
  # Registry URL
  url: ""
  
  # 用户名 (可选，建议使用 docker login)
  username: null
  
  # 密码 (可选，建议使用 docker login)
  password: null
  
  # 是否允许 insecure (http) 连接
  insecure: false

# ========== 日志配置 ==========
log:
  # 控制台日志级别: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL
  level: "INFO"
  
  # 文件日志级别
  file_level: "DEBUG"
  
  # 日志目录
  log_dir: "logs"
  
  # 日志保留天数
  retention_days: 7

# ========== 额外自定义配置 ==========
extra: {}
```

---

## 🐍 Python API 使用

除了命令行，你也可以在 Python 代码中调用 Flowcontainer。

### 基础用法

```python
from Flowcontainer import ImageBuilder, ConfigManager

# 加载配置（自动搜索 Flowcontainer.yaml）
config = ConfigManager()

# 创建构建器
builder = ImageBuilder(config)

# 构建镜像
result = builder.build(
    env_file="/path/to/rsem.yaml",
    tag="rnaflow-rsem:0.1",
    push=False,
)

# 查看结果
print(f"状态: {result.status}")          # success / failed
print(f"镜像ID: {result.image_id}")
print(f"大小: {result.image_size}")
print(f"耗时: {result.duration:.1f}秒")
```

### 批量构建

```python
from pathlib import Path
from Flowcontainer import ImageBuilder, ConfigManager, ContainerEnvYaml

config = ConfigManager()
builder = ImageBuilder(config)

# 批量构建
results = builder.batch_build(
    env_dir=Path("../envs/"),
    push=False,
)

# 更新 container_env.yaml
env_yaml = ContainerEnvYaml(Path("container_env.yaml"))
env_yaml.update(results)

# 打印摘要
from Flowcontainer.builder import print_build_summary
print_build_summary(results)
```

### 检查 Registry

```python
from Flowcontainer.docker_client import RegistryChecker

# 检查 Docker Daemon
can_connect, msg = RegistryChecker.check_docker_daemon()
print(f"Docker: {msg}")

# 检查 Registry
can_connect, msg = RegistryChecker.check_registry("registry.example.com")
print(f"Registry: {msg}")
```

---

## 📊 输出文件

### container_env.yaml

构建完成后自动生成的镜像记录，供后续使用：

```yaml
images:
  rnaflow-rsem:
    tag: rnaflow-rsem:0.1
    registry: registry.example.com/
    full_image_uri: registry.example.com/rnaflow-rsem:0.1
    image_id: abc123def456
    image_digest: sha256:xxx...
    size: 1.2GB
    created_at: "2024-01-15T10:30:00"
    env_file: /absolute/path/to/rsem.yaml
    tools: [rsem, samtools]
    pushed: true
    push_time: "2024-01-15T10:35:00"

metadata:
  last_updated: "2024-01-15T10:35:00"
  total_images: 1
  version: "1.0"
```

### 日志文件

- 控制台日志：Rich 美化实时输出
- 文件日志：`logs/flowcontainer_YYYYMMDD.log`
- 日志保留：默认 7 天自动清理

---

## 🔗 Snakemake 整合示例

在 Snakemake 中使用 Flowcontainer 构建的镜像：

```python
# 读取 container_env.yaml 中的镜像信息
import yaml

with open("container_env.yaml") as f:
    env_config = yaml.safe_load(f)

rsem_image = env_config["images"]["rnaflow-rsem"]["full_image_uri"]

# 在 Snakefile 中使用
rule rsem_calculate_expression:
    input:
        bam="samples/{sample}.bam",
        ref="reference/rsem_index"
    output:
        "results/{sample}/genes.results"
    container:
        f"docker://{rsem_image}"
    shell:
        "rsem-calculate-expression --paired-end {input.bam} {input.ref} {wildcards.sample}"
```

---

## 🧪 Flowcontainer Pipeline 测试

`test_pipeline/` 目录包含用于测试 Flowcontainer 镜像集成的 Snakemake 工作流。

### 📁 文件结构

```
test_pipeline/
├── Snakefile          # 测试工作流
└── README.md          # 测试文档
```

### 🚀 快速开始

#### 1. 查看可用镜像

```bash
cd test_pipeline
snakemake -c 1 list_available_images
```

这会读取 `../container_env.yaml` 并列出所有可用镜像。

#### 2. 本地运行测试（不使用容器）

```bash
# 运行所有测试
snakemake -c 1

# 或运行特定测试
snakemake -c 1 test_rsem_container
snakemake -c 1 test_samtools_container
```

#### 3. 使用容器运行测试（推荐）

```bash
# 需要安装 singularity 或 apptainer
snakemake -c 1 --use-singularity
```

### 📋 测试规则说明

| 规则名 | 说明 | 使用的镜像 |
|--------|------|-----------|
| `test_rsem_container` | 测试 RSEM 容器 | `rnaflow-rsem` |
| `test_samtools_container` | 测试 Samtools（自动查找） | 根据工具名自动查找 |
| `multi_tool_in_one_container` | 同一容器中多工具测试 | `rnaflow-rsem` |
| `dynamic_image_selection` | 动态选择镜像 | 根据配置选择 |
| `list_available_images` | 列出可用镜像 | 无（纯 Python） |

### 🔧 关键功能展示

#### 1. 读取 container_env.yaml

```python
import yaml

# 自动加载配置
with open("../container_env.yaml") as f:
    config = yaml.safe_load(f)

IMAGES = config.get("images", {})
```

#### 2. 使用特定镜像

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

#### 3. 根据工具自动选择镜像

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

### 📝 动态配置

创建 `workflow_config.yaml` 覆盖默认配置：

```yaml
rsem_image: "test-rsem"  # 选择不同的镜像
test_mode: true          # 启用测试模式
```

然后运行：

```bash
snakemake -c 1 dynamic_image_selection --use-singularity
```

### 🔍 查看结果

测试完成后查看结果：

```bash
# 查看测试结果
cat results/rsem_test_completed.txt
cat results/samtools_test_completed.txt
cat results/multi_tool_test.txt

# 查看可用镜像列表
cat results/available_images.txt
```

### 🧹 清理

```bash
snakemake clean
```

---

## 🛠️ 高级用法

### 自定义 Dockerfile 模板

创建自定义模板 `my_template.dockerfile`：

```dockerfile
FROM condaforge/mambaforge:latest
LABEL maintainer="Your Name"

WORKDIR /opt
COPY {{env_file}} /tmp/environment.yaml
RUN mamba env create -f /tmp/environment.yaml -n {{env_name}} -y && \
    mamba clean -afy

ENV PATH=/opt/conda/envs/{{env_name}}/bin:$PATH

{% if health_check_cmd %}
HEALTHCHECK CMD {{health_check_cmd}} || exit 1
{% endif %}

CMD ["/bin/bash"]
```

在配置中指定：

```yaml
build:
  template_file: "/path/to/my_template.dockerfile"
```

### 使用私有 Registry

```yaml
# Flowcontainer.yaml
registry:
  url: "registry.example.com"
  insecure: false  # 如果使用自签名证书设为 true

build:
  default_registry: "registry.example.com/bioinfo/"
```

或者命令行：

```bash
# 先 docker login
docker login registry.example.com

# 然后构建推送
flowcontainer build -e envs/rsem.yaml --push
```

---

## ❓ 常见问题

### Q1: 安装后命令找不到？

确保 pip 安装路径在 PATH 中：

```bash
# 查看安装位置
which flowcontainer

# 如果找不到，尝试
pip install --user -e .
export PATH=$HOME/.local/bin:$PATH
```

### Q2: Docker 连接失败？

```bash
# 检查 Docker 是否运行
sudo systemctl status docker

# 检查权限
docker ps

# 如果需要，将用户加入 docker 组
sudo usermod -aG docker $USER
# 然后重新登录
```

### Q3: Registry 推送失败？

```bash
# 先检查连通性
flowcontainer doctor --registry registry.example.com

# 确保已登录
docker login registry.example.com

# 检查镜像标签是否正确
docker images | grep your-image
```

### Q4: 如何避免生成 __pycache__？

Flowcontainer 已自动设置 `sys.dont_write_bytecode = True`，不会生成 `__pycache__`。

如果你也想在全局禁用：

```bash
export PYTHONDONTWRITEBYTECODE=1
```

### Q5: 如何调试详细日志？

```bash
# 临时提高日志级别
flowcontainer build -e envs/test.yaml --log-level DEBUG

# 或者在配置中修改
log:
  level: "DEBUG"
```

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 许可证

MIT License

---

## 📮 联系方式

如有问题或建议，欢迎通过以下方式联系：

- GitHub Issues: [提交问题](https://github.com/yourusername/flowcontainer/issues)
- Email: your.email@example.com
