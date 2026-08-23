from __future__ import annotations

from typing import Any


def api_service_directory() -> dict[str, Any]:
    """Return the administrator-only catalog of FileMaker integration APIs."""

    return {
        "services": [
            {
                "name": "FileMaker 签名会话桥接",
                "description": "验证 FileMaker 签名函数生成的 ctx / sig，并签发短期 WebViewer 会话。",
                "direction": "FileMaker WebViewer → DMS",
                "authentication": "HMAC-SHA256 签名；后续请求使用 Bearer Token",
                "icon": "key",
                "endpoints": [
                    {"method": "POST", "path": "/api/webviewer/session"},
                    {"method": "GET", "path": "/api/webviewer/session/me"},
                ],
            },
            {
                "name": "员工智能问答服务",
                "description": "接收 FileMaker 内嵌对话请求，并按账号权限查询实时业务数据。",
                "direction": "FileMaker WebViewer → DMS → FileMaker",
                "authentication": "WebViewer 会话 + 智能问答权限",
                "icon": "message",
                "endpoints": [
                    {"method": "POST", "path": "/api/natural-query"},
                ],
            },
            {
                "name": "产品库存流水服务",
                "description": "按当前产品编号返回只读库存摘要、趋势与出入库流水。",
                "direction": "FileMaker WebViewer → DMS → FileMaker",
                "authentication": "WebViewer 会话 + 库存查看权限",
                "icon": "database",
                "endpoints": [
                    {
                        "method": "GET",
                        "path": "/api/products/{productSku}/inventory-transactions",
                    },
                ],
            },
            {
                "name": "内部订单合并服务",
                "description": "读取客户订单、生成合并预览，并通过专用受控通道写入 FileMaker。",
                "direction": "FileMaker WebViewer → DMS → FileMaker",
                "authentication": "WebViewer 会话 + 订单/合并权限",
                "icon": "orders",
                "endpoints": [
                    {"method": "GET", "path": "/api/orders/internal"},
                    {
                        "method": "POST",
                        "path": "/api/orders/internal/merge/preview",
                    },
                    {
                        "method": "POST",
                        "path": "/api/orders/internal/merge/web",
                    },
                ],
            },
            {
                "name": "零件编号服务",
                "description": "为 WebViewer 和 FileMaker 原生脚本提供选项、相关零件和编号生成。",
                "direction": "FileMaker WebViewer / 原生脚本 → DMS → FileMaker",
                "authentication": "WebViewer 会话；原生直调使用 ctx / sig",
                "icon": "code",
                "endpoints": [
                    {"method": "GET", "path": "/api/material-ids/options"},
                    {"method": "GET", "path": "/api/material-ids/related-parts"},
                    {"method": "POST", "path": "/api/material-ids/generate"},
                    {
                        "method": "GET",
                        "path": "/api/material-ids/filemaker-generate",
                    },
                ],
            },
            {
                "name": "新建零件与附件服务",
                "description": "提供参考选项、厂商搜索、表单校验、建档和 COS 图片绑定。",
                "direction": "FileMaker WebViewer → DMS → FileMaker / COS",
                "authentication": "WebViewer 会话 + 零件建立权限",
                "icon": "package",
                "endpoints": [
                    {"method": "GET", "path": "/api/part-creation/options"},
                    {"method": "GET", "path": "/api/part-creation/vendors"},
                    {"method": "POST", "path": "/api/part-creation/validate"},
                    {"method": "POST", "path": "/api/part-creation/create"},
                    {"method": "POST", "path": "/api/part-assets/uploads/*"},
                ],
            },
            {
                "name": "夜间报告与 Dashboard 服务",
                "description": "查询HTML归档报告、结构化指标、重要异常及最近运行趋势。",
                "direction": "DMS 夜间任务 → 报告存储 → 内部工作台",
                "authentication": "有效的内部员工 WebViewer 会话",
                "icon": "report",
                "endpoints": [
                    {"method": "GET", "path": "/api/reports"},
                    {"method": "GET", "path": "/api/reports/dashboard"},
                    {"method": "GET", "path": "/api/reports/{reportId}"},
                    {"method": "GET", "path": "/api/reports/{reportId}/html"},
                ],
            },
            {
                "name": "MES 回调与 FileMaker 回写",
                "description": "接收外部事件、排队重试，并由后台 worker 调用 FileMaker 布局或脚本。",
                "direction": "MES → DMS → FileMaker",
                "authentication": "API Key 或 HMAC 签名",
                "icon": "webhook",
                "endpoints": [
                    {"method": "POST", "path": "/api/mes/callback"},
                    {"method": "POST", "path": "/api/mes/callback/{source}"},
                ],
            },
            {
                "name": "二维码生成服务",
                "description": "把业务数据或短令牌生成为 PNG / SVG 二维码。",
                "direction": "FileMaker / 内部系统 → DMS",
                "authentication": "内部服务调用；不包含业务数据读取",
                "icon": "qr",
                "endpoints": [
                    {"method": "POST", "path": "/api/qrcode/generate"},
                ],
            },
        ]
    }
