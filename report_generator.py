#!/usr/bin/env python3
"""
JMeter JTL 文件 -> Grafana 风格 HTML 报告生成器

用法:
    python report_generator.py input.jtl [-o output.html]
"""
import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

from jtl_parser import parse_jtl
from metrics import calculate_metrics, percentile, TimeSeriesPoint


def safe_str(value, default=""):
    """安全转换字符串，处理 None 和特殊字符"""
    if value is None:
        return default
    return html.escape(str(value))


def to_json(value):
    """序列化为 JSON 并转义 '</'，防止内联 <script> 被数据中的 </script> 提前闭合"""
    return json.dumps(value, ensure_ascii=False).replace('</', '<\\/')


def generate_report(data, output_path: str, source_file: str = ""):
    """生成 HTML 报告"""
    metrics = calculate_metrics(data)

    if metrics.total_samples == 0:
        print("警告：没有有效的样本数据")
        return False

    # 读取模板
    template_path = Path(__file__).parent / "report_template.html"
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    # 计算状态
    if metrics.error_rate < 1:
        status_class = "status-ok"
        status_text = "健康"
    elif metrics.error_rate < 5:
        status_class = "status-warning"
        status_text = "警告"
    else:
        status_class = "status-error"
        status_text = "严重"

    # 错误率颜色
    error_color = "#10b981" if metrics.error_rate < 1 else ("#f59e0b" if metrics.error_rate < 5 else "#ef4444")

    # 源文件名称
    file_name = Path(source_file).name if source_file else "unknown.jtl"

    # 百分位计算相对于 max 的百分比
    max_rt = metrics.max_rt or 1
    min_pct = min((metrics.min_rt / max_rt) * 100, 100) if max_rt > 0 else 0
    median_pct = min((metrics.median_rt / max_rt) * 100, 100) if max_rt > 0 else 0
    p90_pct = min((metrics.p90_rt / max_rt) * 100, 100) if max_rt > 0 else 0
    p95_pct = min((metrics.p95_rt / max_rt) * 100, 100) if max_rt > 0 else 0
    p99_pct = min((metrics.p99_rt / max_rt) * 100, 100) if max_rt > 0 else 0

    # 时间序列数据准备 - 如果数据点太多则进行降采样
    time_labels = []
    rt_data = []
    throughput_data = []
    error_data = []

    if metrics.time_series:
        base_ts = metrics.time_series[0].timestamp
        raw_data = list(metrics.time_series)

        # 降采样：如果数据点超过 200 个，则进行聚合
        max_points = 200
        if len(raw_data) > max_points:
            import math
            step = math.ceil(len(raw_data) / max_points)
            sampled_data = []
            for i in range(0, len(raw_data), step):
                chunk = raw_data[i:i+step]
                if chunk:
                    avg_rt = sum(p.avg_rt for p in chunk) / len(chunk)
                    total_count = sum(p.count for p in chunk)
                    total_errors = sum(p.error_count for p in chunk)
                    span_sec = (chunk[-1].timestamp - chunk[0].timestamp) / 1000 + 1
                    sampled_data.append(TimeSeriesPoint(
                        timestamp=chunk[0].timestamp,
                        count=total_count,
                        avg_rt=avg_rt,
                        error_count=total_errors,
                        throughput=total_count / span_sec,
                    ))
            raw_data = sampled_data

        for point in raw_data:
            offset_sec = (point.timestamp - base_ts) // 1000
            time_labels.append(f"{offset_sec}s")
            rt_data.append(round(point.avg_rt, 2))
            throughput_data.append(point.throughput)
            error_data.append(point.error_count)

    # 按标签统计
    label_rows = []
    label_names = []
    label_rt_data = []
    label_p95_data = []
    label_p99_data = []
    label_latency_data = []
    label_connect_data = []
    label_idle_data = []
    label_thread_data = []
    slow_diagnostic_items = []

    # 收集所有 URL 用于明细模块
    all_urls_data = []
    all_query_params_data = []  # 请求参数明细

    for label, stats in sorted(metrics.label_stats.items(), key=lambda x: x[1].count, reverse=True):
        label_error_rate = (stats.error_count / stats.count * 100) if stats.count > 0 else 0
        label_p95 = percentile(stats.rt_values, 95) if stats.rt_values else 0
        label_p99 = percentile(stats.rt_values, 99) if stats.rt_values else 0
        label_avg = sum(stats.rt_values) / len(stats.rt_values) if stats.rt_values else 0
        label_latency_avg = sum(stats.latency_values) / len(stats.latency_values) if stats.latency_values else 0
        label_connect_avg = sum(stats.connect_time_values) / len(stats.connect_time_values) if stats.connect_time_values else 0
        label_idle_avg = sum(stats.idle_time_values) / len(stats.idle_time_values) if stats.idle_time_values else 0
        url_count = len(stats.url_set)
        avg_threads = int(stats.avg_concurrent_threads)
        total_sample_count = stats.total_sample_count
        total_error_count = stats.total_error_count

        # 截断过长的标签名
        display_label = label[:50] + "..." if len(label) > 50 else label

        label_rows.append(f"""
            <tr data-interface-name="{safe_str(label)}">
                <td class="label-name" title="{safe_str(label)}">{safe_str(display_label)}</td>
                <td data-value="{stats.count}">{stats.count:,}</td>
                <td data-value="{stats.success_count}" style="color: #10b981;">{stats.success_count:,}</td>
                <td data-value="{stats.error_count}" style="color: #ef4444;">{stats.error_count:,}</td>
                <td data-value="{label_error_rate:.4f}">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div class="progress-bar" style="background: #2a2f3a; border-radius: 3px; height: 6px; min-width: 80px; overflow: hidden;">
                            <div style="height: 100%; background: {'#ef4444' if label_error_rate > 5 else '#f59e0b' if label_error_rate > 1 else '#10b981'}; border-radius: 3px; width: {min(label_error_rate, 100)}%"></div>
                        </div>
                        <span style="color: {'#ef4444' if label_error_rate > 5 else '#f59e0b' if label_error_rate > 1 else '#10b981'}">{label_error_rate:.2f}%</span>
                    </div>
                </td>
                <td data-value="{label_avg:.4f}">{label_avg:.2f} ms</td>
                <td data-value="{label_p95:.4f}">{label_p95:.2f} ms</td>
                <td data-value="{label_p99:.4f}">{label_p99:.2f} ms</td>
                <td data-value="{stats.max_rt}">{stats.min_rt} / {stats.max_rt} ms</td>
                <td data-value="{label_latency_avg:.4f}">{label_latency_avg:.2f} ms</td>
                <td data-value="{label_connect_avg:.4f}">{label_connect_avg:.2f} ms</td>
                <td data-value="{label_idle_avg:.4f}">{label_idle_avg:.2f} ms</td>
                <td data-value="{avg_threads}">{avg_threads}</td>
                <td data-value="{total_sample_count}">{total_sample_count:,}</td>
                <td data-value="{total_error_count}">{total_error_count:,}</td>
                <td>{url_count}</td>
            </tr>
        """)

        slow_diagnostic_items.append({
            'label': label,
            'display_label': display_label,
            'count': stats.count,
            'avg': label_avg,
            'p95': label_p95,
            'p99': label_p99,
            'max': stats.max_rt,
        })

        # 收集 URL 数据
        for url in list(stats.url_set)[:20]:  # 每个接口最多取 20 个 URL
            all_urls_data.append({
                'label': display_label,
                'full_label': label,
                'url': url,
                'count': stats.count,
            })

        # 收集请求参数数据（从 URL 中提取查询参数）
        for url in list(stats.url_set)[:20]:
            from urllib.parse import urlparse, parse_qs
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                for param_name, values in params.items():
                    all_query_params_data.append({
                        'label': display_label,
                        'param_name': param_name,
                        'param_value': values[0] if values else '',
                    })
            except Exception:
                pass

        label_names.append(display_label)
        label_rt_data.append(round(label_avg, 2))
        label_p95_data.append(round(label_p95, 2))
        label_p99_data.append(round(label_p99, 2))
        label_latency_data.append(round(label_latency_avg, 2))
        label_connect_data.append(round(label_connect_avg, 2))
        label_idle_data.append(round(label_idle_avg, 2))
        label_thread_data.append(avg_threads)

    # 慢接口诊断部分
    slow_diagnostics_section = ""
    if slow_diagnostic_items:
        top_n = 10

        def metric_value_html(value):
            return f"{value:,.2f} ms"

        def build_metric_rows(metric_key, metric_label):
            top_items = sorted(slow_diagnostic_items, key=lambda x: x[metric_key], reverse=True)[:top_n]
            return "".join([
                f"""
                <button class="slow-diagnostic-row" type="button" data-focus-interface="{safe_str(item['label'])}" title="{safe_str(item['label'])}">
                    <span class="slow-rank">#{index}</span>
                    <span class="slow-name">{safe_str(item['display_label'])}</span>
                    <span class="slow-value">{metric_value_html(item[metric_key])}</span>
                </button>
                """
                for index, item in enumerate(top_items, start=1)
            ])

        metric_configs = [
            ('avg', '平均 RT'),
            ('p95', 'P95 RT'),
            ('p99', 'P99 RT'),
            ('max', 'Max RT'),
        ]

        rank_scores = {}
        for metric_key, _ in metric_configs:
            top_items = sorted(slow_diagnostic_items, key=lambda x: x[metric_key], reverse=True)[:top_n]
            for index, item in enumerate(top_items):
                entry = rank_scores.setdefault(item['label'], {
                    'label': item['label'],
                    'display_label': item['display_label'],
                    'score': 0,
                    'p95': item['p95'],
                    'p99': item['p99'],
                    'max': item['max'],
                })
                entry['score'] += top_n - index

        priority_items = sorted(
            rank_scores.values(),
            key=lambda x: (x['score'], x['p95'], x['p99'], x['max']),
            reverse=True
        )[:3]

        priority_html = "".join([
            f"""
            <button class="slow-priority-item" type="button" data-focus-interface="{safe_str(item['label'])}" title="{safe_str(item['label'])}">
                {safe_str(item['display_label'])}
            </button>
            """
            for item in priority_items
        ])

        metric_panels = "".join([
            f"""
            <div class="slow-diagnostic-panel">
                <div class="slow-diagnostic-title">{safe_str(metric_label)} Top {top_n}</div>
                <div class="slow-diagnostic-list">
                    {build_metric_rows(metric_key, metric_label)}
                </div>
            </div>
            """
            for metric_key, metric_label in metric_configs
        ])

        slow_diagnostics_section = f"""
        <div class="table-card slow-diagnostics-card">
            <h3>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 3v18h18"/>
                    <path d="M7 15l4-4 3 3 5-7"/>
                </svg>
                慢接口 Top {top_n} 诊断
            </h3>
            <div class="slow-priority-bar">
                <span class="slow-priority-label">优先关注</span>
                <div class="slow-priority-list">
                    {priority_html}
                </div>
            </div>
            <div class="slow-diagnostics-grid">
                {metric_panels}
            </div>
        </div>
        """

    # 错误信息部分
    error_section = ""
    if metrics.error_summary:
        error_items = sorted(metrics.error_summary.items(), key=lambda x: x[1], reverse=True)
        error_html = "".join([
            f'<div class="error-item"><span class="message" title="{safe_str(msg)}">{safe_str(msg[:100])}{"..." if len(msg) > 100 else ""}</span><span class="count">{cnt:,}</span></div>'
            for msg, cnt in error_items[:50]  # 最多显示 50 条
        ])
        error_section = f"""
        <div class="table-card">
            <h3>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                错误信息 Top 50
            </h3>
            <div class="error-list">
                {error_html}
            </div>
        </div>
        """
    else:
        error_section = """
        <div class="table-card">
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                <p>测试执行成功，未发生错误</p>
            </div>
        </div>
        """

    # URL 明细部分
    url_section = ""
    if all_urls_data:
        url_rows = []
        for item in all_urls_data[:1000]:  # 最多显示 1000 条
            url_rows.append(f"""
                <tr data-detail-interface-name="{safe_str(item['full_label'])}">
                    <td class="label-name" title="{safe_str(item['label'])}">{safe_str(item['label'])}</td>
                    <td style="color: var(--text-secondary); word-break: break-all;">{safe_str(item['url'])}</td>
                    <td>{item['count']:,}</td>
                </tr>
            """)

        url_section = f"""
        <div class="table-card">
            <h3>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
                </svg>
                URL 明细列表 (Top 1000)
            </h3>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>接口名称</th>
                            <th>URL</th>
                            <th>请求数</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(url_rows)}
                    </tbody>
                </table>
            </div>
        </div>
        """

    # 请求参数与响应参数详情部分
    request_response_section = ""
    request_response_rows = []

    # 增加样本数据量限制，从 100 提升到 500
    max_samples_per_label = 500
    max_display_rows = 300  # 最多显示 300 条详情

    for label, stats in sorted(metrics.label_stats.items(), key=lambda x: x[1].count, reverse=True):
        # 从 sample_data 中提取请求参数和响应参数 - 增加样本数量
        for sample in stats.sample_data[:max_samples_per_label]:
            query_string = sample.get('query_string', '')
            response_data = sample.get('response_data', '')

            # 只要有请求或响应数据就显示
            if query_string or response_data:
                # 请求参数展示 - 支持折叠
                request_html = ""
                if query_string:
                    request_length = len(query_string)
                    # 尝试解析为查询参数格式
                    try:
                        from urllib.parse import parse_qs
                        parsed = parse_qs(query_string) if query_string else {}
                        if parsed:
                            param_items = []
                            for param_name, values in parsed.items():
                                param_value = values[0] if values else ""
                                param_items.append(f'<span class="param-item"><span class="param-name">{safe_str(param_name)}</span>=<span class="param-value">{safe_str(param_value)}</span></span>')
                            query_params_formatted = ', '.join(param_items)
                            # 如果解析后的参数较少，直接显示；否则用折叠
                            if request_length < 500:
                                request_html = f'<div class="request-content"><pre class="param-pre">{query_params_formatted}</pre></div>'
                            else:
                                preview = safe_str(query_string[:500]) + '...'
                                request_html = f'''<details class="expandable-content">
                                    <summary class="expand-summary">
                                        <span class="summary-icon">▶</span>
                                        <span class="summary-text">查看请求参数 ({request_length} 字符)</span>
                                    </summary>
                                    <div class="expanded-content">
                                        <pre class="param-pre">{safe_str(query_string)}</pre>
                                    </div>
                                </details>'''
                        else:
                            # 无法解析的格式（如 multipart）
                            if request_length < 500:
                                request_html = f'<div class="request-content"><pre class="param-pre">{safe_str(query_string)}</pre></div>'
                            else:
                                preview = safe_str(query_string[:500]) + '...'
                                request_html = f'''<details class="expandable-content">
                                    <summary class="expand-summary">
                                        <span class="summary-icon">▶</span>
                                        <span class="summary-text">查看请求参数 ({request_length} 字符)</span>
                                    </summary>
                                    <div class="expanded-content">
                                        <pre class="param-pre">{safe_str(query_string)}</pre>
                                    </div>
                                </details>'''
                    except Exception:
                        if request_length < 500:
                            request_html = f'<div class="request-content"><pre class="param-pre">{safe_str(query_string)}</pre></div>'
                        else:
                            request_html = f'''<details class="expandable-content">
                                <summary class="expand-summary">
                                    <span class="summary-icon">▶</span>
                                    <span class="summary-text">查看请求参数 ({request_length} 字符)</span>
                                </summary>
                                <div class="expanded-content">
                                    <pre class="param-pre">{safe_str(query_string)}</pre>
                                </div>
                            </details>'''
                else:
                    request_html = '<span class="no-data">无请求参数</span>'

                # 响应数据展示 - 支持折叠，增加显示内容量
                response_html = ""
                if response_data:
                    response_length = len(response_data)
                    # 增加截断阈值到 5000 字符
                    truncate_threshold = 5000

                    if response_length <= truncate_threshold:
                        # 直接显示完整响应
                        response_html = f'<div class="response-content"><pre class="response-pre">{safe_str(response_data)}</pre></div>'
                    else:
                        # 超过阈值，显示折叠版本
                        response_html = f'''<details class="expandable-content">
                            <summary class="expand-summary">
                                <span class="summary-icon">▶</span>
                                <span class="summary-text">查看响应数据 ({response_length} 字符)</span>
                            </summary>
                            <div class="expanded-content">
                                <pre class="response-pre">{safe_str(response_data)}</pre>
                            </div>
                        </details>'''
                else:
                    response_html = '<span class="no-data">无响应数据</span>'

                request_response_rows.append(f"""
                    <tr data-detail-interface-name="{safe_str(label)}">
                        <td class="label-name" title="{safe_str(label)}">{safe_str(label[:60])}</td>
                        <td class="param-cell">
                            {request_html}
                        </td>
                        <td class="response-cell">
                            {response_html}
                        </td>
                    </tr>
                """)

            # 限制总行数，避免页面过大
            if len(request_response_rows) >= max_display_rows:
                break

        if len(request_response_rows) >= max_display_rows:
            break

    if request_response_rows:
        # 如果超过最大显示行数，添加提示信息
        overflow_hint = ""
        if len(request_response_rows) >= max_display_rows:
            overflow_hint = f'<span style="font-size: 12px; color: var(--text-muted); margin-left: 10px;">(共 {len(request_response_rows)} 条，仅显示前 {max_display_rows} 条)</span>'

        request_response_section = f"""
        <div class="table-card">
            <h3>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18"/>
                </svg>
                请求参数与响应参数详情 {overflow_hint}
            </h3>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th style="min-width: 200px;">接口名称</th>
                            <th style="min-width: 350px;">请求参数 (点击展开)</th>
                            <th style="min-width: 450px;">响应参数 (点击展开)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(request_response_rows)}
                    </tbody>
                </table>
            </div>
        </div>
        """

    # 替换模板变量
    # 动态计算标签图表高度：每个接口约 38 像素，最少 350px
    label_chart_height = max(350, len(label_names) * 38 + 40)

    replacements = {
        "{{status_class}}": status_class,
        "{{status_text}}": status_text,
        "{{generated_time}}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "{{file_name}}": safe_str(file_name),
        "{{total_samples}}": f"{metrics.total_samples:,}",
        "{{duration}}": f"{metrics.duration_seconds:.2f}",
        "{{avg_rt}}": f"{metrics.avg_rt:.2f}",
        "{{throughput}}": f"{metrics.throughput:.2f}",
        "{{error_rate}}": f"{metrics.error_rate:.2f}",
        "{{error_color}}": error_color,
        "{{min_rt}}": str(int(metrics.min_rt)),
        "{{median_rt}}": f"{metrics.median_rt:.2f}",
        "{{p90_rt}}": f"{metrics.p90_rt:.2f}",
        "{{p95_rt}}": f"{metrics.p95_rt:.2f}",
        "{{p99_rt}}": f"{metrics.p99_rt:.2f}",
        "{{max_rt}}": str(int(metrics.max_rt)),
        "{{min_pct}}": f"{min_pct:.1f}",
        "{{median_pct}}": f"{median_pct:.1f}",
        "{{p90_pct}}": f"{p90_pct:.1f}",
        "{{p95_pct}}": f"{p95_pct:.1f}",
        "{{p99_pct}}": f"{p99_pct:.1f}",
        "{{time_labels}}": to_json(time_labels),
        "{{rt_data}}": to_json(rt_data),
        "{{throughput_data}}": to_json(throughput_data),
        "{{error_data}}": to_json(error_data),
        "{{label_names}}": to_json(label_names),
        "{{label_rt_data}}": to_json(label_rt_data),
        "{{label_rows}}": "".join(label_rows) if label_rows else '<tr><td colspan="16" class="empty-state">无数据</td></tr>',
        "{{slow_diagnostics_section}}": slow_diagnostics_section,
        "{{error_section}}": error_section,
        "{{url_section}}": url_section,
        "{{request_response_section}}": request_response_section,
        "{{label_chart_height}}": str(label_chart_height),
        "{{avg_latency}}": f"{metrics.avg_latency:.2f}",
        "{{avg_connect_time}}": f"{metrics.avg_connect_time:.2f}",
        "{{avg_idle_time}}": f"{metrics.avg_idle_time:.2f}",
        "{{unique_urls}}": f"{metrics.unique_urls:,}",
        "{{avg_concurrent_threads}}": f"{metrics.avg_concurrent_threads:.1f}",
    }

    html_content = template
    for key, value in replacements.items():
        html_content = html_content.replace(key, str(value))

    # 写入输出
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"报告已生成：{output_path}")
    print(f"  - 总样本数：{metrics.total_samples:,}")
    print(f"  - 持续时间：{metrics.duration_seconds:.2f}s")
    print(f"  - 平均 RT: {metrics.avg_rt:.2f}ms")
    print(f"  - 吞吐量：{metrics.throughput:.2f} req/s")
    print(f"  - 错误率：{metrics.error_rate:.2f}%")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="JMeter JTL -> Grafana 风格 HTML 报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python report_generator.py test.jtl
    python report_generator.py test.jtl -o report.html
        """
    )
    parser.add_argument("input", help="输入的 JTL 文件路径")
    parser.add_argument("-o", "--output", help="输出的 HTML 文件路径", default="report.html")

    args = parser.parse_args()

    try:
        data = parse_jtl(args.input)
        generate_report(data, args.output or "report.html")
    except FileNotFoundError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
