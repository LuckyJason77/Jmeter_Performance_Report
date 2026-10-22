#!/usr/bin/env python3
"""
JMeter 报告批量生成器

自动扫描 input 目录下的所有 .jtl 文件，为每个文件生成 HTML 报告到 output 目录

用法:
    python batch_generator.py
"""
import html
import sys
import traceback
import urllib.parse
from pathlib import Path

from report_generator import generate_report
from jtl_parser import parse_jtl


# 目录配置
SCRIPT_DIR = Path(__file__).parent
INPUT_DIR = SCRIPT_DIR / "input"      # JTL 文件输入目录
OUTPUT_DIR = SCRIPT_DIR / "output"    # HTML 报告输出目录


def ensure_dirs():
    """确保输入输出目录存在"""
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)


def find_jtl_files():
    """查找 input 目录下所有 JTL 文件"""
    jtl_files = list(INPUT_DIR.glob("*.jtl"))
    jtl_files.extend(INPUT_DIR.glob("*.JTL"))
    # 去重（大小写可能重复）
    seen = set()
    unique_files = []
    for f in jtl_files:
        if f.name.lower() not in seen:
            seen.add(f.name.lower())
            unique_files.append(f)
    return sorted(unique_files)


def copy_template_assets():
    """复制必要的资源文件到 output 目录（如果需要离线使用）"""
    # 当前版本使用 CDN，此功能预留
    pass


def main():
    print("=" * 60)
    print("JMeter 报告批量生成器")
    print("=" * 60)

    # 确保目录存在
    ensure_dirs()

    # 查找 JTL 文件
    jtl_files = find_jtl_files()

    if not jtl_files:
        print(f"\n未在 input 目录找到任何 .jtl 文件")
        print(f"请将 JTL 文件放入：{INPUT_DIR}")
        print("\n支持的格式:")
        print("  - CSV 格式 (.jtl)")
        print("  - XML 格式 (.jtl)")
        sys.exit(0)

    print(f"\n发现 {len(jtl_files)} 个 JTL 文件:")
    for f in jtl_files:
        print(f"  - {f.name}")

    print(f"\n输出目录：{OUTPUT_DIR}")
    print("-" * 60)

    # 生成报告
    success_count = 0
    error_count = 0
    reports = []

    for jtl_file in jtl_files:
        try:
            # 解析 JTL
            print(f"\n处理：{jtl_file.name} ...")
            data = parse_jtl(str(jtl_file))

            if data.samples:
                print(f"  解析到 {len(data.samples):,} 条样本 ({data.format} 格式)")
            else:
                print(f"  警告：未解析到有效数据")

            # 生成报告
            report_name = jtl_file.stem + "_report.html"
            output_path = OUTPUT_DIR / report_name

            if generate_report(data, str(output_path), str(jtl_file)):
                reports.append((jtl_file.name, report_name, len(data.samples)))
                success_count += 1
            else:
                print(f"  跳过：{jtl_file.name}（无有效样本，未生成报告）")
                error_count += 1

        except Exception as e:
            print(f"  错误：{e}")
            traceback.print_exc()
            error_count += 1

    # 生成索引页面
    if reports:
        generate_index(reports)

    # 汇总
    print("\n" + "=" * 60)
    print("生成完成!")
    print("=" * 60)
    print(f"成功：{success_count} | 失败：{error_count}")
    print(f"\n报告输出目录：{OUTPUT_DIR}")
    print(f"索引页面：{OUTPUT_DIR / 'index.html'}")

    if success_count > 0:
        print("\n查看报告:")
        print(f"  1. 打开 {OUTPUT_DIR} 目录")
        print(f"  2. 双击 index.html 查看所有报告列表")
        print(f"  3. 或单独打开各个报告 HTML 文件")


def generate_index(reports):
    """生成索引页面"""
    from datetime import datetime

    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>性能测试报告索引</title>
    <style>
        :root {{
            --bg-primary: #0b0c0e;
            --bg-secondary: #141619;
            --bg-card: #1a1d21;
            --text-primary: #d1d5db;
            --text-secondary: #9ca3af;
            --border-color: #2a2f3a;
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 40px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            margin-bottom: 40px;
        }}

        h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
        }}

        .subtitle {{
            color: var(--text-secondary);
            font-size: 14px;
        }}

        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}

        .stat-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
        }}

        .stat-card .label {{
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .stat-card .value {{
            font-size: 28px;
            font-weight: 700;
            margin-top: 8px;
        }}

        .report-list {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
        }}

        .report-list h2 {{
            font-size: 16px;
            padding: 16px 20px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
        }}

        .report-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
            transition: background 0.15s;
        }}

        .report-item:hover {{
            background: var(--bg-secondary);
        }}

        .report-item:last-child {{
            border-bottom: none;
        }}

        .report-info {{
            flex: 1;
        }}

        .report-name {{
            font-weight: 500;
            margin-bottom: 4px;
        }}

        .report-meta {{
            font-size: 13px;
            color: var(--text-secondary);
        }}

        .report-link {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 10px 16px;
            background: var(--accent-blue);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            transition: opacity 0.2s;
        }}

        .report-link:hover {{
            opacity: 0.9;
        }}

        footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 24px;
            border-top: 1px solid var(--border-color);
            color: var(--text-secondary);
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>性能测试报告索引</h1>
            <p class="subtitle">生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </header>

        <div class="stats">
            <div class="stat-card">
                <div class="label">报告总数</div>
                <div class="value" style="color: var(--accent-blue)">{len(reports)}</div>
            </div>
            <div class="stat-card">
                <div class="label">总样本数</div>
                <div class="value" style="color: var(--accent-green)">{sum(r[2] for r in reports):,}</div>
            </div>
            <div class="stat-card">
                <div class="label">源文件数</div>
                <div class="value">{len(reports)}</div>
            </div>
        </div>

        <div class="report-list">
            <h2>报告列表</h2>
            {''.join([f"""
            <div class="report-item">
                <div class="report-info">
                    <div class="report-name">{html.escape(r[0])}</div>
                    <div class="report-meta">{r[2]:,} 条样本</div>
                </div>
                <a class="report-link" href="{urllib.parse.quote(r[1])}" target="_blank">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                        <polyline points="15 3 21 3 21 9"/>
                        <line x1="10" y1="14" x2="21" y2="3"/>
                    </svg>
                    查看报告
                </a>
            </div>
            """ for r in reports])}
        </div>

        <footer>
            <p>Generated by JMeter Report Generator</p>
        </footer>
    </div>
</body>
</html>
"""

    index_path = OUTPUT_DIR / "index.html"
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)
    print(f"已生成索引页面：{index_path}")


if __name__ == "__main__":
    main()
