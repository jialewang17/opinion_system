"""
HTML渲染模块
"""
import json
import shutil
from pathlib import Path
from typing import Dict, List, Any
from jinja2 import Environment, FileSystemLoader
from ..utils.paths import bucket, get_project_root
from ..utils.logging import setup_logger

def build_integrated_report(topic: str, date: str, logger=None) -> Path:
    """
    构建整合HTML报告
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        Path: 生成的HTML文件路径
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    logger.info(f"开始构建整合HTML报告")
    
    try:
        # 设置Jinja2环境
        project_root = get_project_root()
        templates_dir = project_root / "templates"
        
        if not templates_dir.exists():
            logger.error(f"模板目录不存在: {templates_dir}")
            return None
        
        env = Environment(loader=FileSystemLoader(str(templates_dir)))
        
        # 渲染整合报告模板
        template = env.get_template("reports.html.j2")
        
        # 收集processed文件夹中的HTML图表
        processed_dir = bucket("processed", topic, date)
        reports_dir = bucket("reports", topic, date)
        
        if not processed_dir.exists():
            logger.error(f"未找到分析结果目录: {processed_dir}")
            return None
        
        # 收集八大功能的图表和解读
        function_data = {}
        function_names = {
            "volume": "声量分析",
            "attitude": "态度分析", 
            "trends": "趋势分析",
            "keywords": "关键词分析",
            "theme": "主题分析",
            "geography": "地域分析",
            "publishers": "发布机构分析",
            "highlights": "重点议题分析"
        }
        
        for func_name, func_display in function_names.items():
            func_dir = processed_dir / func_name
            if func_dir.exists():
                function_data[func_name] = {
                    "display_name": func_display,
                    "channels": {}
                }
                
                # 查找所有子目录（包括总体和各渠道）
                subdirs = [d for d in func_dir.iterdir() if d.is_dir()]
                
                # 确保总体在最前面
                sorted_subdirs = []
                overall_dir = func_dir / "总体"
                if overall_dir.exists():
                    sorted_subdirs.append(("总体", overall_dir))
                
                # 添加其他渠道
                for subdir in subdirs:
                    if subdir.name != "总体":
                        sorted_subdirs.append((subdir.name, subdir))
                
                for channel_name, subdir in sorted_subdirs:
                    # 查找HTML图表文件
                    html_files = list(subdir.glob("*.html"))
                    chart_html = ""
                    if html_files:
                        with open(html_files[0], 'r', encoding='utf-8') as f:
                            chart_html = f.read()
                        logger.info(f"找到图表文件: {func_name}/{channel_name}")
                    else:
                        logger.warning(f"未找到HTML图表文件: {func_name}/{channel_name}")
                    
                    # 查找AI解读文件
                    ai_file = reports_dir / func_name / channel_name / "解读.txt"
                    ai_text = ""
                    if ai_file.exists():
                        with open(ai_file, 'r', encoding='utf-8') as f:
                            ai_text = f.read()
                        logger.info(f"找到AI解读文件: {func_name}/{channel_name}")
                    else:
                        logger.warning(f"未找到AI解读文件: {func_name}/{channel_name}")
                    
                    # 设置显示名称
                    if channel_name == "总体":
                        display_name = "总体分析"
                    else:
                        display_name = f"{channel_name}渠道"
                    
                    function_data[func_name]["channels"][channel_name] = {
                        "display_name": display_name,
                        "chart_html": chart_html,
                        "ai_text": ai_text
                    }
                
                logger.info(f"收集功能数据: {func_name}，共{len(function_data[func_name]['channels'])}个渠道")
            else:
                logger.warning(f"功能目录不存在: {func_name}")
        
        # 准备模板变量
        template_vars = {
            "topic": topic,
            "date": date,
            "function_data": function_data
        }
        
        # 渲染HTML
        html_content = template.render(**template_vars)
        
        # 保存HTML文件到results文件夹
        results_dir = bucket("results", topic, date)
        results_dir.mkdir(parents=True, exist_ok=True)
        html_file = results_dir / "整合报告.html"
        
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"整合HTML报告已生成: {html_file}")
        return html_file
        
    except Exception as e:
        logger.error(f"构建整合HTML报告失败: {e}")
        return None

def generate_chart_data(chart_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成图表数据
    
    Args:
        chart_config (Dict[str, Any]): 图表配置
    
    Returns:
        Dict[str, Any]: ECharts配置
    """
    chart_type = chart_config.get("type", "bar")
    data = chart_config.get("data", [])
    title = chart_config.get("title", "")
    
    if chart_type == "pie":
        return {
            "type": "pie",
            "title": {"text": title},
            "series": [{
                "type": "pie",
                "radius": "50%",
                "data": data
            }]
        }
    
    elif chart_type == "bar":
        x_data = [item["name"] for item in data]
        y_data = [item["value"] for item in data]
        
        return {
            "type": "bar",
            "title": {"text": title},
            "xAxis": {"type": "category", "data": x_data},
            "yAxis": {"type": "value"},
            "series": [{
                "type": "bar",
                "data": y_data
            }]
        }
    
    elif chart_type == "line":
        x_data = [item["name"] for item in data]
        y_data = [item["value"] for item in data]
        
        return {
            "type": "line",
            "title": {"text": title},
            "xAxis": {"type": "category", "data": x_data},
            "yAxis": {"type": "value"},
            "series": [{
                "type": "line",
                "data": y_data
            }]
        }
    
    return chart_config

def build_report(report_data: Dict[str, Any], topic: str, date: str, logger=None) -> Path:
    """
    构建HTML报告（保持兼容性）
    
    Args:
        report_data (Dict[str, Any]): 报告数据
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        Path: 生成的HTML文件路径
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    logger.info(f"开始构建HTML报告")
    
    try:
        # 设置Jinja2环境
        project_root = get_project_root()
        templates_dir = project_root / "templates"
        
        if not templates_dir.exists():
            logger.error(f"模板目录不存在: {templates_dir}")
            return None
        
        env = Environment(loader=FileSystemLoader(str(templates_dir)))
        
        # 渲染主报告模板
        template = env.get_template("report.html.j2")
        
        # 准备模板变量
        template_vars = {
            "topic": topic,
            "date": date,
            "report_data": report_data,
            "analysis_results": report_data.get("analysis_results", {}),
            "ai_explanations": report_data.get("ai_explanations", {}),
            "summary": report_data.get("summary", {})
        }
        
        # 渲染HTML
        html_content = template.render(**template_vars)
        
        # 保存HTML文件
        reports_dir = bucket("reports", topic, date)
        html_file = reports_dir / "index.html"
        
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"HTML报告已生成: {html_file}")
        return html_file
        
    except Exception as e:
        logger.error(f"构建HTML报告失败: {e}")
        return None
