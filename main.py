"""
OpinionSystem 舆情分析系统主程序
"""
import sys
import json
import click
import asyncio
import warnings
from pathlib import Path

# 严格抑制所有警告（在导入其他模块之前）
warnings.filterwarnings("ignore")  # 抑制所有警告
warnings.simplefilter("ignore")  # 设置默认过滤器为忽略
# 特别抑制常见警告类型
warnings.filterwarnings("ignore", message=".*pkg_resources.*")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
# 抑制 openpyxl 的默认样式警告
warnings.filterwarnings("ignore", message="workbook contains no default style, apply openpyxl's default")

def _ensure_src_on_path() -> None:
    """确保src目录在Python路径中"""
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

def main() -> None:
    """主程序入口"""
    _ensure_src_on_path()
    cli()

@click.group()
def cli():
    """
    OpinionSystem 舆情分析系统命令行工具
    """
    pass

@cli.command('TopicBertopic')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=False, help='结束日期 (YYYY-MM-DD)，如果不提供则使用start作为单日期')
@click.option('--userdict', required=False, help='可选：用户词典路径，默认 configs/userdict.txt')
@click.option('--stopwords', required=False, help='可选：停用词路径，默认 configs/stopwords.txt')
def topic_bertopic(topic, start, end, userdict, stopwords):
    """
    运行BERTopic+Qwen主题分析（基于数据库数据）
    """
    from src.topic import run_topic_bertopic
    ok = run_topic_bertopic(topic, start, end_date=end, fetch_dir=None, userdict=userdict, stopwords=stopwords)
    if not ok:
        date_range = f"{start}_{end}" if end else start
        print(f"TopicBertopic 运行失败: {topic} - {date_range}")

@cli.command('FluidAnalysis')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=False, help='结束日期 (YYYY-MM-DD)，如果不提供则使用start作为单日期')
@click.option('--window-hours', default=3, type=int, help='时间窗口大小（小时），默认3小时')
@click.option('--file', required=False, help='可选：指定要分析的文件名（例如: 论坛.csv），只分析该文件')
def fluid_analysis(topic, start, end, window_hours, file):
    """
    运行舆论流体动力学指标计算与热度预测（基于数据库数据）
    """
    from src.fluid import run_fluid_analysis
    ok = run_fluid_analysis(topic, start, end_date=end, window_hours=window_hours, target_file=file)
    if not ok:
        date_range = f"{start}_{end}" if end else start
        print(f"FluidAnalysis 运行失败: {topic} - {date_range}")

@cli.command('Merge')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def trs_merge(topic, date):
    """
    合并TRS Excel文件
    """
    from src.merge import run_merge
    
    result = run_merge(topic, date)
    if not result:
        print(f"合并失败: {topic} - {date}")

@cli.command('Clean')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def clean(topic, date):
    """
    清洗数据
    """
    from src.clean import run_clean
    
    result = run_clean(topic, date)
    if not result:
        print(f"清洗失败: {topic} - {date}")

@cli.command('Filter')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def ai_filter(topic, date):
    """
    AI相关性筛选
    """
    from src.filter import run_filter
    
    result = run_filter(topic, date)
    if not result:
        print(f"筛选失败: {topic} - {date}")

@cli.command('Upload')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def upload(topic, date):
    """
    上传数据到数据库
    """
    from src.update import run_update
    
    result = run_update(topic, date)
    if not result:
        print(f"上传失败: {topic} - {date}")

@cli.command('Query')
def query():
    """
    查询数据库信息
    """
    from src.query import run_query
    
    result = run_query()
    if not result:
        print("查询失败")

@cli.command('Fetch')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def fetch(topic, start, end):
    """
    从数据库获取数据
    """
    from src.fetch import run_fetch
    
    result = run_fetch(topic, start, end)
    if not result:
        print(f"提取失败: {topic} - {start} 到 {end}")

@cli.command('Analyze')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
@click.option('--func', help='指定分析函数')
def analyze(topic, start, end, func):
    """
    运行数据分析
    """
    from src.analyze import run_Analyze
    
    result = run_Analyze(topic, start, end_date=end, only_function=func)
    if not result:
        print(f"分析失败: {topic} - {start} 到 {end}")

@cli.command('ContentAnalyze')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def content_analyze(topic, start, end):
    """
    运行内容分析
    """
    from src.contentanalyze import run_content_analysis_sync
    
    result = run_content_analysis_sync(topic, start, end)
    if not result:
        print(f"内容分析失败: {topic} - {start} 到 {end}")

@cli.command('Explain')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
@click.option('--func', help='指定解读函数（仅运行单个功能）')
@click.option('--only-overall', is_flag=True, default=False, help='仅运行总体类型的解读任务（不包括渠道）')
def explain(topic, start, end, func, only_overall):
    """
    运行数据解读
    
    使用方式：
    1. 运行所有解读功能：python main.py Explain --topic 测试 --start 2025-09-23 --end 2025-09-23
    2. 仅运行单个功能：python main.py Explain --topic 测试 --start 2025-09-23 --end 2025-09-23 --func bertopic
    3. 仅运行所有总体类型：python main.py Explain --topic 测试 --start 2025-09-23 --end 2025-09-23 --only-overall
    """
    import asyncio
    from src.explain import run_Explain
    
    result = asyncio.run(run_Explain(topic, start, end_date=end, only_function=func, only_overall=only_overall))
    if not result:
        print(f"解读失败: {topic} - {start} 到 {end}")

@cli.command('Report')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def report(topic, start, end):
    """
    生成DOCX报告
    """
    from src.report import run_report
    
    result = run_report(topic, start, end)
    if not result:
        print(f"报告生成失败: {topic} - {start} 到 {end}")

@cli.command('DataPipeline')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def data_pipeline(topic, date):
    """
    数据清洗和存储流水线（使用单日期）
    """
    from src.merge import run_merge
    from src.clean import run_clean
    from src.filter import run_filter
    from src.update import run_update
        
    # 1. 合并TRS数据
    if not run_merge(topic, date):
        print("合并步骤失败")
        return False
    
    # 2. 数据清洗
    if not run_clean(topic, date):
        print("清洗步骤失败")
        return False
    
    # 3. AI筛选
    if not run_filter(topic, date):
        print("筛选步骤失败")
        return False
    
    # 4. 数据上传
    if not run_update(topic, date):
        print("上传步骤失败")
        return False
    
    return True

@cli.command('AnalyzePipeline')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def analysis_pipeline(topic, start, end):
    """
    数据分析流水线（使用时间范围）
    """
    from src.fetch import run_fetch
    from src.analyze import run_Analyze
        
    # 1. 提数
    if not run_fetch(topic, start, end):
        print("提取步骤失败")
        return False
    
    # 2. 数据分析
    if not run_Analyze(topic, start, end_date=end):
        print("分析步骤失败")
        return False
    
    return True

@cli.command('TagVectorize')
@click.option('--topic', default='控烟', help='RAG主题名称（如"控烟"）')
def tagrag(topic):
    """
    运行TagRAG向量化功能
    """
    from src.utils.rag.tagrag.tag_vec_data import vectorize_and_store
    
    try:
        dataset = vectorize_and_store(topic_name=topic)
        return True
    except Exception as e:
        return False

# 后续将融入系统中，后续可删除
@cli.command('TagRetrieve')
@click.option('--query', required=True, help='查询语句')
@click.option('--topic', default='控烟', help='RAG主题名称（如"控烟"）')
@click.option('--search-column', default='tag_vec', help='搜索列 (tag_vec 或 text_vec)')
@click.option('--top-k', default=1, help='返回个数')
@click.option('--return-columns', help='返回列，用逗号分隔 (如: id,text)')
def tag_retrieve_command(query, topic, search_column, top_k, return_columns):
    """
    运行TagRAG检索功能
    """
    from src.utils.rag.tagrag.tag_retrieve_data import tag_retrieve
    
    try:
        # 处理返回列参数
        return_cols = None
        if return_columns:
            return_cols = [col.strip() for col in return_columns.split(',')]
        
        # 执行检索
        result = tag_retrieve(
            query=query,
            topic_name=topic,
            search_column=search_column,
            top_k=int(top_k),
            return_columns=return_cols
        )
        
        # 输出结果
        if result['status'] == 'success':
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"TagRetrieve: {result['error']}")
        
        return True
        
    except Exception as e:
        print(f"TagRetrieve检索处理失败: {e}")
        return False

@cli.command('RouterVectorize')
@click.option('--topic', default='默认', help='RAG主题名称（如"默认"）')
def ragrouter_command(topic):
    """
    运行RagRouter向量化处理功能
    """
    from src.utils.rag.ragrouter.router_vec_data import run_ragrouter
    
    try:
        result = run_ragrouter(topic_name=topic)
        return True
    except Exception as e:
        print(f"RouterVectorize处理失败: {e}")
        return False

# 后续将融入系统中，后续可删除 
@cli.command('RouterRetrieve')
@click.option('--topic', required=True, help='检索主题（如：控烟）')
@click.option('--query', required=True, help='查询语句')
@click.option('--mode', default='mixed', type=click.Choice(['mixed', 'graphrag', 'normalrag', 'tagrag']),
              help='检索模式 (默认: mixed)')
@click.option('--topk-graphrag', default=3, type=int, help='GraphRAG返回的核心实体数量 (默认: 3)')
@click.option('--topk-normalrag', default=10, type=int, help='NormalRAG返回的句子数量 (默认: 5)')
@click.option('--topk-tagrag', default=3, type=int, help='TagRAG返回的文本块数量 (默认: 5)')
@click.option('--no-llm-summary', is_flag=True, help='禁用LLM整理结果')
@click.option('--llm-summary-mode', default='supplement', type=click.Choice(['strict', 'supplement']),
              help='LLM整理模式 (默认: strict)')
@click.option('--return-format', default='llm_only', type=click.Choice(['both', 'llm_only', 'index_only']),
              help='返回格式: both(全部), llm_only(仅LLM), index_only(仅索引) (默认: both)')
def router_retrieve_command(topic, query, mode, topk_graphrag, topk_normalrag, topk_tagrag,
                           no_llm_summary, llm_summary_mode, return_format):
    """
    运行RagRouter检索功能
    """
    from src.utils.rag.ragrouter.router_retrieve_data import router_retrieve
    
    try:
        # 执行检索
        results = router_retrieve(
            topic=topic,
            query=query,
            mode=mode,
            topk_graphrag=topk_graphrag,
            topk_normalrag=topk_normalrag,
            topk_tagrag=topk_tagrag,
            enable_llm_summary=not no_llm_summary,
            llm_summary_mode=llm_summary_mode,
            return_format=return_format
        )
    
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return True
        
    except Exception as e:
        print(f"RouterRetrieve检索失败: {e}")
        return False

if __name__ == "__main__":
    main()
