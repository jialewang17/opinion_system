"""
OpinionSystem 命令行接口
"""
import click
import asyncio
from pathlib import Path
from .utils.logging import setup_logger, log_module_start, log_success, log_error, log_save_success
from .io.trs_import import merge_trs_data
from .cleaning.pipeline import run_clean
from .ai.filter import run_Filter_sync
from .io.databases import upload_cleaned, fetch_range, upload_filtered_excels, fetch_by_config
from .io.query import query_database_info
from .analysis.runner import run_Analyze
from .ai.summarize import run_explain_sync
from .reporting.assemble import assemble_report_data
from .reporting.render_html import build_integrated_report

@click.group()
def cli():
    """
    OpinionSystem 舆情分析系统命令行工具
    """
    pass

@cli.command('Merge')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def trs_merge(topic, date):
    """
    合并TRS Excel文件
    """
    from .io.trs_import import merge_trs_data
    
    logger = setup_logger(topic, date)
    log_module_start(logger, "Merge")
    
    try:
        result = merge_trs_data(topic, date, logger)
        if result:
            log_success(logger, "模块执行完成", "Merge")
        else:
            log_error(logger, "模块执行失败", "Merge")
    except Exception as e:
        log_error(logger, f"模块执行失败: {e}", "Merge")

@cli.command('Clean')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def clean(topic, date):
    """
    清洗数据
    """
    logger = setup_logger(topic, date)
    log_module_start(logger, "Clean")
    
    try:
        result = run_clean(topic, date, logger)
        if result:
            log_success(logger, "模块执行完成", "clean")
        else:
            log_error(logger, "模块执行失败", "clean")
    except Exception as e:
        log_error(logger, f"模块执行失败: {e}", "clean")

@cli.command('Filter')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def ai_filter(topic, date):
    """
    AI相关性筛选
    """
    logger = setup_logger(topic, date)
    log_module_start(logger, "Filter")
    
    try:
        result = run_Filter_sync(topic, date, logger)
        if result:
            log_success(logger, "模块执行完成", "Filter")
        else:
            log_error(logger, "模块执行失败", "Filter")
    except Exception as e:
        log_error(logger, f"模块执行失败: {e}", "Filter")

@cli.command('Upload')
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def upload(topic, date):
    """
    上传数据到数据库
    """
    logger = setup_logger(topic, date)
    log_module_start(logger, "Upload")

    try:
        # 优先尝试 filtered Excel 直传；若无则回退到清洗后的 parquet 上传
        result = upload_filtered_excels(topic, date, logger)
        if not result:
            result = upload_cleaned(topic, date, logger)

        if result:
            log_success(logger, "模块执行完成", "Upload")
        else:
            log_error(logger, "模块执行失败", "Upload")
    except Exception as e:
        log_error(logger, f"模块执行失败: {e}", "Upload")

@cli.command('Query')
def query():
    """
    查询数据库信息
    """
    logger = setup_logger("Query", "info")
    log_module_start(logger, "Query")

    try:
        result = query_database_info(logger)
        if result:
            log_success(logger, "模块执行完成", "Query")
        else:
            log_error(logger, "模块执行失败", "Query")
    except Exception as e:
        log_error(logger, f"模块执行失败: {e}", "Query")

@cli.command('Fetch')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def fetch(topic, start, end):
    """
    从数据库获取数据
    """
    logger = setup_logger(topic, start)
    log_module_start(logger, "Fetch")
    
    try:
        result = fetch_range(topic, start, end, start, logger)
        if result:
            log_success(logger, "模块执行完成", "Fetch")
        else:
            log_error(logger, "模块执行完成", "Fetch")
    except Exception as e:
        log_error(logger, f"模块执行完成: {e}", "Fetch")

@cli.command('Analyze')
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
@click.option('--func', help='指定分析函数')
def analyze(topic, start, end, func):
    """
    运行数据分析
    """
    from .analysis.runner import run_Analyze
    
    logger = setup_logger(topic, start)
    log_module_start(logger, "Analyze")
    
    try:
        # 使用时间范围格式的目录名
        date_range = f"{start}_{end}"
        result = run_Analyze(topic, date_range, logger, func)
        if not result:
            log_error(logger, "模块执行失败", "Analyze")
    except Exception as e:
        log_error(logger, f"模块执行失败: {e}", "Analyze")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def ai_explain(topic, start, end):
    """
    运行AI解读
    """
    from .ai.summarize import run_explain_sync
    
    logger = setup_logger(topic, start)
    log_module_start(logger, "AI解读")
    
    try:
        # 使用时间范围格式的目录名
        date_range = f"{start}_{end}"
        result = asyncio.run(run_explain_sync(topic, date_range, logger))
        if result:
            log_success(logger, "AI解读完成", "ai_explain")
        else:
            log_error(logger, "AI解读失败", "ai_explain")
    except Exception as e:
        log_error(logger, f"AI解读异常: {e}", "ai_explain")


@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def integrated_report(topic, start, end):
    """
    生成整合报告
    """
    logger = setup_logger(topic, start)
    log_module_start(logger, "整合报告生成")
    
    try:
        # 使用时间范围格式的目录名
        date_range = f"{start}_{end}"
        report_data = assemble_report_data(topic, date_range, logger)
        if report_data:
            html_path = build_integrated_report(topic, date_range, logger)
            log_success(logger, "整合报告生成完成", "integrated_report")
            log_save_success(logger, str(html_path), "pipeline")
        else:
            log_error(logger, "整合报告生成失败", "integrated_report")
    except Exception as e:
        log_error(logger, f"整合报告生成异常: {e}", "integrated_report")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def pipeline(topic, date):
    """
    运行完整流水线（数据清洗+分析）
    """
    logger = setup_logger(topic, date)
    log_module_start(logger, "完整流水线")
    
    try:
        # 1. 合并TRS数据
        from .io.trs_import import merge_trs_data
        log_module_start(logger, "1️⃣ 合并TRS数据")
        if not merge_trs_data(topic, date, logger):
            log_error(logger, "TRS数据合并失败", "pipeline")
            return False
        
        # 2. 数据清洗
        log_module_start(logger, "2️⃣ 数据清洗")
        if not run_clean(topic, date, logger):
            log_error(logger, "数据清洗失败", "pipeline")
            return False
        
        # 3. AI筛选
        log_module_start(logger, "3️⃣ AI相关性筛选")
        if not run_Filter_sync(topic, date, logger):
            log_error(logger, "AI相关性筛选失败", "pipeline")
            return False
        
        # 4. 数据上传
        log_module_start(logger, "4️⃣ 数据上传")
        if not upload_filtered_excels(topic, date, logger):
            log_error(logger, "数据上传失败", "pipeline")
            return False
        
        # 5. 数据分析（使用date作为时间范围）
        from .analysis.runner import run_Analyze
        log_module_start(logger, "5️⃣ 数据分析")
        if not run_analysis(topic, date, logger):
            log_error(logger, "数据分析失败", "analyze")
            return False
        
        # 6. AI解读（使用date作为时间范围）
        from .ai.summarize import run_explain_sync
        log_module_start(logger, "6️⃣ AI解读")
        if not asyncio.run(run_explain_sync(topic, date, logger)):
            log_error(logger, "AI解读失败", "ai_explain")
            return False
        
        # 7. 报告生成
        log_module_start(logger, "7️⃣ 报告生成")
        report_data = assemble_report_data(topic, date, logger)
        if report_data:
            html_path = build_integrated_report(topic, date, logger)
            log_save_success(logger, str(html_path), "pipeline")
        
        log_success(logger, "完整流水线执行完成", "pipeline")
        return True
        
    except Exception as e:
        log_error(logger, f"流水线执行异常: {e}", "pipeline")
        return False


@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def data_pipeline(topic, date):
    """
    数据清洗和存储流水线（使用单日期）
    """
    logger = setup_logger(topic, date)
    log_module_start(logger, "数据清洗和存储流水线")
    
    try:
        # 1. 合并TRS数据
        from .io.trs_import import merge_trs_data
        log_module_start(logger, "1️⃣ 合并TRS数据")
        if not merge_trs_data(topic, date, logger):
            log_error(logger, "TRS数据合并失败", "pipeline")
            return False
        
        # 2. 数据清洗
        log_module_start(logger, "2️⃣ 数据清洗")
        if not run_clean(topic, date, logger):
            log_error(logger, "数据清洗失败", "pipeline")
            return False
        
        # 3. AI筛选
        log_module_start(logger, "3️⃣ AI相关性筛选")
        if not run_Filter_sync(topic, date, logger):
            log_error(logger, "AI相关性筛选失败", "pipeline")
            return False
        
        # 4. 数据上传
        log_module_start(logger, "4️⃣ 数据上传")
        if not upload_filtered_excels(topic, date, logger):
            log_error(logger, "数据上传失败", "pipeline")
            return False
        
        log_success(logger, "数据清洗和存储流水线执行完成", "data_pipeline")
        return True
        
    except Exception as e:
        log_error(logger, f"数据流水线执行异常: {e}", "data_pipeline")
        return False


@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def analysis_pipeline(topic, start, end):
    """
    数据分析流水线（使用时间范围）
    """
    logger = setup_logger(topic, start)
    log_module_start(logger, "数据分析流水线")
    
    try:
        # 1. 数据分析
        from .analysis.runner import run_Analyze
        log_module_start(logger, "1️⃣ 数据分析")
        # 使用时间范围格式的目录名
        date_range = f"{start}_{end}"
        if not run_analysis(topic, date_range, logger):
            log_error(logger, "数据分析失败", "analyze")
            return False
        
        # 2. AI解读
        from .ai.summarize import run_explain_sync
        log_module_start(logger, "2️⃣ AI解读")
        if not asyncio.run(run_explain_sync(topic, date_range, logger)):
            log_error(logger, "AI解读失败", "ai_explain")
            return False
        
        # 3. 报告生成
        log_module_start(logger, "3️⃣ 报告生成")
        report_data = assemble_report_data(topic, date_range, logger)
        if report_data:
            html_path = build_integrated_report(topic, date_range, logger)
            log_save_success(logger, str(html_path), "pipeline")
        
        log_success(logger, "数据分析流水线执行完成", "analysis_pipeline")
        return True
        
    except Exception as e:
        log_error(logger, f"分析流水线执行异常: {e}", "analysis_pipeline")
        return False


if __name__ == '__main__':
    cli()
