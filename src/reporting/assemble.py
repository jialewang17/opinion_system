"""
报告组装模块
"""
import json
from pathlib import Path
from typing import Dict, List, Any
from ..utils.paths import bucket
from ..utils.logging import setup_logger

def assemble_report_data(topic: str, date: str, logger=None) -> Dict[str, Any]:
    """
    组装报告数据
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 组装后的报告数据
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    logger.info(f"开始组装报告数据")
    
    # 读取分析结果
    processed_dir = bucket("processed", topic, date)
    analysis_files = list(processed_dir.glob("*.json"))
    
    if not analysis_files:
        logger.warning("未找到分析结果文件")
        return {}
    
    # 读取AI解读结果
    explain_files = list(processed_dir.glob("*_explain.json"))
    
    # 组装数据
    report_data = {
        "topic": topic,
        "date": date,
        "analysis_results": {},
        "ai_explanations": {},
        "summary": {}
    }
    
    # 读取分析结果
    for file_path in analysis_files:
        if file_path.stem.endswith('_explain') or file_path.stem == 'analysis_summary':
            continue
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                analysis_data = json.load(f)
                report_data["analysis_results"][file_path.stem] = analysis_data
        except Exception as e:
            logger.error(f"读取分析结果 {file_path.name} 失败: {e}")
            continue
    
    # 读取AI解读结果
    for file_path in explain_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                explain_data = json.load(f)
                analysis_name = explain_data.get("analysis", file_path.stem)
                report_data["ai_explanations"][analysis_name] = explain_data
        except Exception as e:
            logger.error(f"读取AI解读 {file_path.name} 失败: {e}")
            continue
    
    # 生成汇总信息
    try:
        summary_file = processed_dir / "analysis_summary.json"
        if summary_file.exists():
            with open(summary_file, 'r', encoding='utf-8') as f:
                summary_data = json.load(f)
                report_data["summary"] = summary_data
    except Exception as e:
        logger.error(f"读取分析汇总失败: {e}")
    
    # 添加元数据
    report_data["metadata"] = {
        "generated_at": Path(__file__).stat().st_mtime,
        "total_analysis": len(report_data["analysis_results"]),
        "total_explanations": len(report_data["ai_explanations"])
    }
    
    logger.info(f"报告数据组装完成，分析结果: {len(report_data['analysis_results'])}, AI解读: {len(report_data['ai_explanations'])}")
    
    return report_data

def save_report_data(report_data: Dict[str, Any], topic: str, date: str, logger=None) -> Path:
    """
    保存报告数据
    
    Args:
        report_data (Dict[str, Any]): 报告数据
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        Path: 保存的文件路径
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    try:
        reports_dir = bucket("reports", topic, date)
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存JSON格式的报告数据
        json_file = reports_dir / "report_data.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
        
        logger.info(f"报告数据已保存到: {json_file}")
        return json_file
        
    except Exception as e:
        logger.error(f"保存报告数据失败: {e}")
        return None
