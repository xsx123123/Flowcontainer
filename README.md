# RNAFlow Container Builder

RNAFlow 自动容器镜像构建工具 - 根据 Conda 环境 YAML 文件自动生成并构建 Docker 镜像。

## 📁 目录结构

```
container_env/
├── build_image.py          # 核心构建脚本
├── images/
│   └── Dockerfile.template # Dockerfile 模板
├── logs/                   # 构建日志
├── README.md               # 本文档
└── example_snakemake_integration.md  # Snakemake 整合示例
```

## 🚀 快速开始

### 1. 构建单个环境

```bash
cd container_env
python build_image.py -e ../envs/bwa2.yaml -t rnaflow-bwa:v2
```

### 2. 批量构建所有环境

```bash
python build_image.py --batch ../envs/ --registry your-registry.io/
```

### 3. 构建并推送

```bash
python build_image.py -e ../envs/fastqc.yaml -t rnaflow-fastqc:v2 --push --registry registry.io/
```

## 📝 命令行参数

| 参数 | 说明 |
|------|------|
| `-e, --env` | Conda 环境 YAML 文件路径 |
| `-t, --tag` | 镜像标签（如 `rnaflow-bwa:v2`） |
| `-r, --registry` | 镜像仓库前缀（如 `registry.io/`） |
| `--push` | 构建后推送镜像 |
| `--batch DIR` | 批量构建目录中的所有 YAML |
| `--no-cache` | 不使用 Docker 缓存 |
| `--verbose, -v` | 显示详细日志 |

## 🐳 镜像特性

- ✅ **命令直接运行**：`docker run --rm rnaflow-bwa:v2 bwa-mem2 version`
- ✅ **交互式自动激活**：`docker run -it rnaflow-bwa:v2` 自动进入环境
- ✅ **健康检查**：自动检测关键工具
- ✅ **日志记录**：自动保存到 `logs/` 目录
- ✅ **Rich 美化**：彩色终端输出和表格

## 🔗 Snakemake 整合

详见 `example_snakemake_integration.md`

```python
rule bwa_index:
    input:
        ref="genome.fa"
    output:
        "genome.fa.bwt"
    container:
        "rnaflow-bwa:v2"
    shell:
        "bwa-mem2 index {input.ref}"
```

## 📊 日志文件

- 终端日志：`logs/container_build_YYYYMMDD.log`
- JSON 报告：`logs/build_report_YYYYMMDD_HHMMSS.json`
