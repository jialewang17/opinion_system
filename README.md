# OpinionSystem · 舆情分析系统

## 一、项目用途
TRS Excel → 清洗对齐（8渠道）→ 千问筛选 → 入库（MySQL）→ 提数 → 分析（8项）→ AI解读 → 网页/PDF报告

## 二、项目架构及对应功能

```
OpinionSystem/
├─ requirements.txt        # 依赖包
├─ README.md               # 说明文档
├─ cli.py                  # 项目根目录CLI启动脚本
├─ .env                    # 环境配置，包含千问大模型APIKEY
├─ configs/
│  ├─ defaults.yaml        # 数据库连接\模型并发设置
│  ├─ channels.yaml        # 渠道及字段规则\时间
│  ├─ analysis.yaml        # 分析维度
│  └─ prompts.yaml         # 筛选与解读提示词及截断方案
├─ data/
│  ├─ raw/控烟/2025-08-24/        # 原始的trs数据放置位置
│  ├─ staging/控烟/2025-08-24/    # trs数据初步合并后的数据位置
│  ├─ clean/控烟/2025-08-24/      # 数据初步清洗后的位置
│  ├─ filtered/控烟/2025-08-24/   # AI筛选后的数据存放位置
│  ├─ warehouse/控烟/2025-08-24/  # 从数据库提数后的数据位置
│  ├─ processed/控烟/2025-08-24/  # 生成的数据分析图表位置
│  ├─ reports/控烟/2025-08-24/    # AI对图表的解读信息
│  └─ results/控烟/2025-08-24/    # 最终网页报告位置
├─ logs/控烟/2025-08-24/app.log   # 日志存放位置
├─ templates/
│  └─ report.html.j2              # 最终网页报告模板
└─ src/
   ├─ __init__.py
   ├─ cli.py               # 命令行：每步一个命令
   ├─ utils/
   │  ├─ paths.py          # 统一路径：bucket(layer, topic, date)
   │  ├─ logging.py        # 分桶日志
   │  └─ settings.py       # 读取 YAML + .env
   ├─ io/
   │  ├─ trs_import.py     # 合并TRS Excel
   │  ├─ excel.py          # 读写Excel/CSV/Parquet
   │  ├─ db.py             # MySQL 连接
   │  └─ warehouse.py      # 入库/提数
   ├─ cleaning/
   │  ├─ pipeline.py       # 归一→字段映射→去重→文段→清洗→地域/时间
   │  └─ helpers.py        # 小工具：去重/时间解析/地域省级化/文本清理
   ├─ ai/
   │  ├─ qwen.py           # 并发+限流调用
   │  ├─ relevance.py      # 相关性筛选（截断+模板）
   │  └─ summarize.py      # 各分析结果解读
   ├─ analysis/
   │  ├─ runner.py         # 调度分析任务
   │  └─ functions/        # 8个函数各一文件
   │     ├─ volume.py      # 声量
   │     ├─ attitude.py    # 态度
   │     ├─ trends.py      # 趋势
   │     ├─ keywords.py    # 关键词
   │     ├─ theme.py       # 议题聚类
   │     ├─ geography.py   # 地域
   │     ├─ publishers.py  # 发布机构
   │     └─ highlights.py  # 重点议题（调用AI）
   └─ reporting/
      ├─ assemble.py       # 报告数据组装
      └─ render_html.py    # HTML报告渲染
```

## 三、使用指南

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置

```bash
# 构造环境配置
# 创建文件 .env
# 编辑 .env 文件，填入API密钥
DASHSCOPE_API_KEY=sk-7b22413bfe8845b3bc59613d43903793
```

### 3. 使用流程

#### （1）数据导入部分

从TRS系统上下载回数据，在`data/raw`文件夹下创建子文件夹，命名为当天日期，如`2025-01-15`，将TRS数据放入。

**运行数据清洗和存储流水线：**
```bash
python cli.py data-pipeline --topic 控烟 --date 2025-01-15
```

将自动执行：合并 → 清洗 → AI筛选 → 入库等流程

#### （2）数据分析部分

数据分析部分，需要使用`--start 2025-01-01 --end 2025-01-31`命令格式，划分出时间范围。

**运行数据分析流水线：**
```bash
python cli.py analysis-pipeline --topic 控烟 --start 2025-01-01 --end 2025-01-31
```

将自动执行：提数 → 分析 → AI解读 → 生成报告等流程

#### （3）允许单功能使用

**数据导入和处理（使用单日期）：**
```bash
# 合并 TRS Excel
python main.py trs-merge --topic 测试 --date 2025-01-01
# 清洗成8张表
python cli.py clean --topic 控烟 --date 2025-01-15

# AI筛选
python cli.py ai-filter --topic 控烟 --date 2025-01-15

# 入库
python cli.py upload --topic 控烟 --date 2025-01-15
```

**数据分析（使用时间范围）：**
```bash
# 提数
python cli.py fetch --topic 控烟 --start 2025-01-01 --end 2025-01-31

# 分析
# 整体分析
python cli.py analyze --topic 控烟 --start 2025-01-01 --end 2025-01-31
# 单功能分析
python cli.py analyze --topic 控烟 --start 2025-01-01 --end 2025-01-31 --func theme

# AI解读
python cli.py ai-explain --topic 控烟 --start 2025-01-01 --end 2025-01-31

# 生成报告
python cli.py integrated-report --topic 控烟 --start 2025-01-01 --end 2025-01-31
```

**流水线命令：**
```bash
# 完整流水线（数据清洗+分析）
python cli.py pipeline --topic 控烟 --date 2025-01-15

# 数据清洗和存储流水线
python cli.py data-pipeline --topic 控烟 --date 2025-01-15

# 数据分析流水线
python cli.py analysis-pipeline --topic 控烟 --start 2025-01-01 --end 2025-01-31
```

## 四、注意事项

1. **日期格式**：请使用标准格式 `YYYY-MM-DD`，如 `2025-01-15`
2. **时间范围**：使用时间范围的命令会自动创建 `start_end` 格式的目录名
3. **执行顺序**：建议先运行数据分析，再运行AI解读
4. **路径结构**：系统会自动创建必要的目录结构，无需手动创建

## 五、核心功能

- **数据清洗**: 8渠道数据标准化、去重、字段映射
- **AI筛选**: 千问API相关性判断，并发限流
- **数据分析**: 8项分析（声量、态度、趋势、关键词、议题、地域、发布机构、重点）
- **智能解读**: AI自动解读分析结果
- **报告生成**: HTML网页 + PDF报告
- **项目迁移**: 支持环境变量配置，自动路径检测




python main.py Merge --topic 测试 --date 2025-01-01 
python main.py Clean --topic 测试 --date 2025-01-01
python main.py Filter --topic 测试 --date 2025-01-01
python main.py Upload --topic 测试 --date 2025-01-01
python main.py Query
python main.py Fetch --topic 测试 --start 2025-08-24 --end 2025-08-27
python main.py Analyze --topic 测试 --start 2025-08-24 --end 2025-08-27 --func attitude