"""
OpinionSystem 命令行接口
"""
import click
import asyncio
from pathlib import Path
from .utils.logging import setup_logger, log_module_start, log_success, log_error, log_save_success
from .utils.paths import print_project_info, ensure_project_structure, get_project_root
from .utils.settings import settings
from .io.trs_import import merge_trs_data
from .cleaning.pipeline import run_clean
from .ai.relevance import run_filter_sync
from .io.warehouse import upload_cleaned, fetch_range, upload_filtered_excels, fetch_by_config
from .analysis.runner import run_analysis
from .ai.summarize import run_explain_sync
from .reporting.assemble import assemble_report_data, save_report_data
from .reporting.render_html import build_report, build_integrated_report

@click.group()
def cli():
    """
    OpinionSystem 舆情分析系统命令行工具
    """
    pass

@cli.command()
def info():
    """
    显示项目路径和配置信息
    """
    print_project_info()
    print("\n" + "="*50 + "\n")
    settings.print_config_summary()

@cli.command()
def setup():
    """
    设置项目目录结构
    """
    log_module_start(click.echo, "项目设置")
    ensure_project_structure()
    log_success(click.echo, "项目目录结构设置完成")

@cli.command()
def validate():
    """
    验证项目配置
    """
    log_module_start(click.echo, "配置验证")
    if settings.validate_configs():
        log_success(click.echo, "所有配置验证通过")
    else:
        log_error(click.echo, "配置验证失败，请检查配置文件")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def trs_merge(topic, date):
    """
    合并TRS Excel文件
    """
    from .io.trs_import import merge_trs_data
    
    logger = setup_logger(topic, date)
    log_module_start(logger, "TRS数据合并")
    
    try:
        result = merge_trs_data(topic, date, logger)
        if result:
            log_success(logger, "TRS数据合并完成")
            log_save_success(logger, str(result))
        else:
            log_error(logger, "TRS数据合并失败")
    except Exception as e:
        log_error(logger, f"TRS数据合并异常: {e}")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def clean(topic, date):
    """
    清洗数据
    """
    logger = setup_logger(topic, date)
    log_module_start(logger, "数据清洗")
    
    try:
        result = run_clean(topic, date, logger)
        if result:
            log_success(logger, "数据清洗完成")
        else:
            log_error(logger, "数据清洗失败")
    except Exception as e:
        log_error(logger, f"数据清洗异常: {e}")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def ai_filter(topic, date):
    """
    AI相关性筛选
    """
    logger = setup_logger(topic, date)
    log_module_start(logger, "AI相关性筛选")
    
    try:
        result = run_filter_sync(topic, date, logger)
        if result:
            log_success(logger, "AI相关性筛选完成")
        else:
            log_error(logger, "AI相关性筛选失败")
    except Exception as e:
        log_error(logger, f"AI相关性筛选异常: {e}")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--date', required=True, help='日期 (YYYY-MM-DD)')
def upload(topic, date):
    """
    上传数据到数据库
    """
    logger = setup_logger(topic, date)
    log_module_start(logger, "数据上传")
    
    try:
        # 优先尝试 filtered Excel 直传；若无则回退到清洗后的 parquet 上传
        result = upload_filtered_excels(topic, date, logger)
        if not result:
            result = upload_cleaned(topic, date, logger)
        
        if result:
            log_success(logger, "数据上传完成")
        else:
            log_error(logger, "数据上传失败")
    except Exception as e:
        log_error(logger, f"数据上传异常: {e}")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
def fetch(topic, start, end):
    """
    从数据库获取数据
    """
    logger = setup_logger(topic, start)
    log_module_start(logger, "数据获取")
    
    try:
        result = fetch_range(topic, start, end, start, logger)
        if result:
            log_success(logger, "数据获取完成")
        else:
            log_error(logger, "数据获取失败")
    except Exception as e:
        log_error(logger, f"数据获取异常: {e}")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
def fetch_config(topic):
    """
    根据配置获取数据
    """
    logger = setup_logger(topic, "config")
    log_module_start(logger, "配置数据获取")
    
    try:
        # 从defaults.yaml读取时间范围
        result = fetch_by_config(topic, "latest", logger)
        if result:
            log_success(logger, "配置数据获取完成")
        else:
            log_error(logger, "配置数据获取失败")
    except Exception as e:
        log_error(logger, f"配置数据获取异常: {e}")

@cli.command()
@click.option('--topic', required=True, help='专题名称')
@click.option('--start', required=True, help='开始日期 (YYYY-MM-DD)')
@click.option('--end', required=True, help='结束日期 (YYYY-MM-DD)')
@click.option('--func', help='指定分析函数')
def analyze(topic, start, end, func):
    """
    运行数据分析
    """
    from .analysis.runner import run_analysis
    
    logger = setup_logger(topic, start)
    log_module_start(logger, "数据分析")
    
    try:
        # 使用时间范围格式的目录名
        date_range = f"{start}_{end}"
        result = run_analysis(topic, date_range, logger, func)
        if result:
            log_success(logger, "数据分析完成")
        else:
            log_error(logger, "数据分析失败")
    except Exception as e:
        log_error(logger, f"数据分析异常: {e}")

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
            log_success(logger, "AI解读完成")
        else:
            log_error(logger, "AI解读失败")
    except Exception as e:
        log_error(logger, f"AI解读异常: {e}")


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
            log_success(logger, "整合报告生成完成")
            log_save_success(logger, str(html_path))
        else:
            log_error(logger, "整合报告生成失败")
    except Exception as e:
        log_error(logger, f"整合报告生成异常: {e}")

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
            log_error(logger, "TRS数据合并失败")
            return False
        
        # 2. 数据清洗
        log_module_start(logger, "2️⃣ 数据清洗")
        if not run_clean(topic, date, logger):
            log_error(logger, "数据清洗失败")
            return False
        
        # 3. AI筛选
        log_module_start(logger, "3️⃣ AI相关性筛选")
        if not run_filter_sync(topic, date, logger):
            log_error(logger, "AI相关性筛选失败")
            return False
        
        # 4. 数据上传
        log_module_start(logger, "4️⃣ 数据上传")
        if not upload_filtered_excels(topic, date, logger):
            log_error(logger, "数据上传失败")
            return False
        
        # 5. 数据分析（使用date作为时间范围）
        from .analysis.runner import run_analysis
        log_module_start(logger, "5️⃣ 数据分析")
        if not run_analysis(topic, date, logger):
            log_error(logger, "数据分析失败")
            return False
        
        # 6. AI解读（使用date作为时间范围）
        from .ai.summarize import run_explain_sync
        log_module_start(logger, "6️⃣ AI解读")
        if not asyncio.run(run_explain_sync(topic, date, logger)):
            log_error(logger, "AI解读失败")
            return False
        
        # 7. 报告生成
        log_module_start(logger, "7️⃣ 报告生成")
        report_data = assemble_report_data(topic, date, logger)
        if report_data:
            html_path = build_integrated_report(topic, date, logger)
            log_save_success(logger, str(html_path))
        
        log_success(logger, "完整流水线执行完成")
        return True
        
    except Exception as e:
        log_error(logger, f"流水线执行异常: {e}")
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
            log_error(logger, "TRS数据合并失败")
            return False
        
        # 2. 数据清洗
        log_module_start(logger, "2️⃣ 数据清洗")
        if not run_clean(topic, date, logger):
            log_error(logger, "数据清洗失败")
            return False
        
        # 3. AI筛选
        log_module_start(logger, "3️⃣ AI相关性筛选")
        if not run_filter_sync(topic, date, logger):
            log_error(logger, "AI相关性筛选失败")
            return False
        
        # 4. 数据上传
        log_module_start(logger, "4️⃣ 数据上传")
        if not upload_filtered_excels(topic, date, logger):
            log_error(logger, "数据上传失败")
            return False
        
        log_success(logger, "数据清洗和存储流水线执行完成")
        return True
        
    except Exception as e:
        log_error(logger, f"数据流水线执行异常: {e}")
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
        from .analysis.runner import run_analysis
        log_module_start(logger, "1️⃣ 数据分析")
        # 使用时间范围格式的目录名
        date_range = f"{start}_{end}"
        if not run_analysis(topic, date_range, logger):
            log_error(logger, "数据分析失败")
            return False
        
        # 2. AI解读
        from .ai.summarize import run_explain_sync
        log_module_start(logger, "2️⃣ AI解读")
        if not asyncio.run(run_explain_sync(topic, date_range, logger)):
            log_error(logger, "AI解读失败")
            return False
        
        # 3. 报告生成
        log_module_start(logger, "3️⃣ 报告生成")
        report_data = assemble_report_data(topic, date_range, logger)
        if report_data:
            html_path = build_integrated_report(topic, date_range, logger)
            log_save_success(logger, str(html_path))
        
        log_success(logger, "数据分析流水线执行完成")
        return True
        
    except Exception as e:
        log_error(logger, f"分析流水线执行异常: {e}")
        return False


if __name__ == '__main__':
    cli()
