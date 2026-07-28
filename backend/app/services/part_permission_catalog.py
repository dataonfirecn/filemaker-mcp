from __future__ import annotations

from typing import Any


ACTION_META: dict[str, dict[str, Any]] = {
    "read": {"label": "查看", "description": "查看模块安全字段", "risk": "normal"},
    "create": {"label": "新增", "description": "新增记录或草稿", "risk": "normal"},
    "update": {"label": "编辑", "description": "编辑允许字段", "risk": "normal"},
    "submit": {"label": "提交", "description": "提交审核", "risk": "normal"},
    "approve": {"label": "审核", "description": "批准或驳回", "risk": "high"},
    "publish": {"label": "发布", "description": "发布正式版本", "risk": "high"},
    "upload": {"label": "上传", "description": "上传附件或新版本", "risk": "sensitive"},
    "downloadOriginal": {
        "label": "下载原件",
        "description": "下载未压缩原始文件",
        "risk": "high",
    },
    "export": {"label": "导出", "description": "导出 Excel、PDF 或 CSV", "risk": "high"},
    "link": {"label": "建立关联", "description": "建立或解除业务关联", "risk": "sensitive"},
    "execute": {"label": "执行", "description": "执行入库、出库或打印", "risk": "sensitive"},
    "reverse": {"label": "冲销", "description": "创建反向更正记录", "risk": "high"},
    "bulkUpdate": {"label": "批量操作", "description": "批量更新或处理", "risk": "high"},
}


PART_PERMISSION_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "key": "procurement",
        "label": "采购",
        "description": "供应商、报价、成本、补货与采购记录",
        "modules": (
            ("overview", "采购概览", "采购员、供应状态、周期和备注", ("read", "update")),
            ("suppliers", "供应商", "制造商、询价厂商和外加工厂商", ("read", "update")),
            (
                "quotations",
                "报价与询价",
                "供应商报价、询价和报价附件",
                ("read", "create", "update", "submit", "approve", "upload", "downloadOriginal", "export"),
            ),
            ("cost", "采购成本", "单位成本、实际成本和内部估价", ("read", "update", "submit", "approve", "export")),
            ("replenishment", "补货策略", "MOQ、建议下单和欠料", ("read", "update", "approve")),
            ("purchaseHistory", "采购记录", "采购历史及操作记录", ("read", "create", "export")),
            ("inventoryReference", "库存参考", "批号、入出库和在库数量", ("read", "export")),
            ("specReference", "规格参考", "图面、规格和品检参考", ("read", "downloadOriginal")),
            ("associations", "关联资料", "产品、零件及流程 BOM", ("read", "link")),
            ("files", "采购附件", "规格书、报价和采购附件", ("read", "upload", "downloadOriginal", "export")),
        ),
    },
    {
        "key": "business",
        "label": "业务",
        "description": "客户资料、包装、销售价格与产品关联",
        "modules": (
            ("overview", "业务概览", "对外资料和业务状态", ("read", "update", "approve")),
            ("customerNaming", "客户与命名", "对外名称、英文名称和客户零件号", ("read", "update", "submit", "approve")),
            (
                "packaging",
                "包装资料",
                "Logo、彩盒、纸箱、贴纸和说明书",
                ("read", "update", "submit", "approve", "upload", "downloadOriginal", "export"),
            ),
            (
                "salesPrice",
                "销售价格",
                "客户价、销售价和业务报价",
                ("read", "create", "update", "submit", "approve", "publish", "export"),
            ),
            ("productLinks", "产品关联", "关联产品和零件", ("read", "link", "approve", "bulkUpdate")),
            ("notes", "业务备注", "内部备注和备件说明", ("read", "update", "export")),
            ("customerFiles", "客户文件", "客户图档和业务附件", ("read", "upload", "downloadOriginal", "export")),
            ("processReference", "流程参考", "生产、品检和外加工参考", ("read", "export")),
            ("stockReference", "库存参考", "库存和位置摘要", ("read", "export")),
        ),
    },
    {
        "key": "design",
        "label": "设计",
        "description": "2D/3D、材料规格、尺寸、流程与修改记录",
        "modules": (
            ("overview", "设计概览", "零件、材料和设计状态", ("read", "update", "approve")),
            (
                "drawings2d",
                "2D 图档",
                "2D 图、版本和上传信息",
                ("read", "upload", "downloadOriginal", "submit", "approve", "publish", "export"),
            ),
            (
                "models3d",
                "3D 文件",
                "3D 模型、版本和上传信息",
                ("read", "upload", "downloadOriginal", "submit", "approve", "publish", "export"),
            ),
            ("materialSpec", "材料规格", "材料、规格、重量和热处理", ("read", "update", "submit", "approve", "publish")),
            ("dimensions", "尺寸与公差", "设计尺寸和设计公差", ("read", "update", "submit", "approve", "publish")),
            ("process", "设计流程", "工艺、生产流程和周期", ("read", "update", "submit", "approve", "publish")),
            (
                "changeRequests",
                "修改记录",
                "修改主题、内容、附件和状态",
                ("read", "create", "update", "submit", "approve", "upload", "export"),
            ),
            ("associations", "设计关联", "产品、零件和 BOM 关联", ("read", "link", "submit", "approve", "bulkUpdate")),
            ("referenceFiles", "参考文件", "客户图、打样图和外加工图", ("read", "upload", "downloadOriginal", "export")),
        ),
    },
    {
        "key": "quality",
        "label": "品检",
        "description": "品检规范、检验结果、特采与包装检查",
        "modules": (
            ("overview", "品检概览", "零件、材料和审核状态", ("read",)),
            ("standards", "品检规范", "规范、注意事项和正式版本", ("read", "update", "submit", "approve", "publish")),
            ("dimensions", "检验尺寸", "检查尺寸和检验公差", ("read", "update", "submit", "approve", "publish")),
            ("process", "检验流程", "检验和加工流程", ("read", "update", "submit", "approve")),
            (
                "inspectionResults",
                "检验结果",
                "检验结果、结论和检验人",
                ("read", "create", "update", "submit", "approve", "export"),
            ),
            ("inspectionFiles", "品检附件", "品检图片和文件", ("read", "upload", "downloadOriginal", "export", "bulkUpdate")),
            (
                "specialAcceptance",
                "特采",
                "特采申请、审核和附件",
                ("read", "create", "submit", "approve", "upload", "downloadOriginal", "export"),
            ),
            ("designChangeReference", "设计变更参考", "设计修改单和附件", ("read", "downloadOriginal", "export")),
            ("bomReference", "BOM 参考", "品检产品 BOM 和关联产品", ("read", "export")),
            ("laserReference", "雷雕参考", "雷雕参数、照片和档案", ("read", "downloadOriginal", "export")),
            (
                "packagingExecution",
                "包装检查",
                "包装检查和完成记录",
                ("read", "create", "update", "submit", "approve", "upload", "export"),
            ),
        ),
    },
    {
        "key": "warehouse",
        "label": "仓库",
        "description": "库存、位置、出入库、盘点与库存调整",
        "modules": (
            ("overview", "库存概览", "当前库存、安全库存和提醒", ("read", "export")),
            ("locations", "仓库位置", "仓库和主要/次要位置", ("read", "update", "approve", "bulkUpdate")),
            ("receiving", "入库", "入库、批号、采购单和供应商", ("read", "create", "execute", "reverse", "export")),
            ("issuing", "出库", "出库、领料和订单需求", ("read", "create", "execute", "reverse", "export")),
            ("transactions", "库存流水", "完整库存流水", ("read", "export")),
            ("stocktake", "盘点", "盘点任务、盘点数和差异", ("read", "create", "update", "submit", "approve", "export", "bulkUpdate")),
            ("adjustment", "库存调整", "库存调整申请、批准和冲销", ("read", "create", "submit", "approve", "execute", "reverse")),
            ("shortage", "欠料参考", "欠料、建议下单和已下单", ("read", "export")),
            ("labels", "仓库标签", "发料、收料和位置标签", ("read", "execute", "bulkUpdate")),
            ("associations", "仓库关联", "产品、零件和 BOM 位置", ("read", "link", "bulkUpdate")),
            ("referenceFiles", "作业参考", "图面、品检和雷雕参考", ("read", "downloadOriginal")),
        ),
    },
    {
        "key": "laser",
        "label": "雷雕",
        "description": "雷雕参数、美工档、设备档、照片与治具",
        "modules": (
            ("overview", "雷雕概览", "零件、材料和审核状态", ("read",)),
            ("parameters", "雷雕参数", "雷雕参数和正式版本", ("read", "update", "submit", "approve", "publish")),
            (
                "artwork",
                "美工档",
                "雷雕美工文件和版本",
                ("read", "upload", "downloadOriginal", "submit", "approve", "publish", "export"),
            ),
            (
                "outputFiles",
                "设备档",
                "设备使用雷雕档和版本",
                ("read", "upload", "downloadOriginal", "submit", "approve", "publish"),
            ),
            ("photos", "雷雕照片", "雷雕效果和作业照片", ("read", "upload", "approve", "export")),
            ("fixtures", "雷雕治具", "治具 1-3", ("read", "update", "upload", "approve", "downloadOriginal")),
            ("labels", "雷雕标签", "发料和收料标签", ("read", "execute", "bulkUpdate")),
            ("qualityReference", "品检参考", "已批准品检规范", ("read", "downloadOriginal")),
            ("versionHistory", "版本记录", "参数和文件版本历史", ("read", "export")),
        ),
    },
)


def permission_key(group: str, module: str, action: str) -> str:
    return f"part.{group}.{module}.{action}"


def permission_catalog() -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    for group in PART_PERMISSION_GROUPS:
        modules = []
        for module_key, label, description, actions in group["modules"]:
            modules.append(
                {
                    "key": module_key,
                    "label": label,
                    "description": description,
                    "actions": [
                        {
                            "key": action,
                            **ACTION_META[action],
                            "permission": permission_key(
                                group["key"], module_key, action
                            ),
                        }
                        for action in actions
                    ],
                }
            )
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "description": group["description"],
                "modules": modules,
            }
        )
    return {
        "version": 1,
        "groups": groups,
        "permissionCount": len(PART_PERMISSION_KEYS),
    }


PART_PERMISSION_KEYS = tuple(
    permission_key(group["key"], module_key, action)
    for group in PART_PERMISSION_GROUPS
    for module_key, _label, _description, actions in group["modules"]
    for action in actions
)
PART_PERMISSION_KEY_SET = frozenset(PART_PERMISSION_KEYS)


def empty_part_permissions() -> dict[str, bool]:
    return {key: False for key in PART_PERMISSION_KEYS}


def normalize_part_permissions(
    value: Any,
    *,
    fallback: dict[str, bool] | None = None,
) -> dict[str, bool]:
    source = _json_object(value)
    baseline = fallback or {}
    return {
        key: bool(source[key]) if key in source else bool(baseline.get(key, False))
        for key in PART_PERMISSION_KEYS
    }


def default_part_permissions_for_privilege_set(
    privilege_set: str,
) -> dict[str, bool]:
    normalized = privilege_set.strip().casefold()
    if normalized in {
        "[full access]",
        "full access",
        "[完全访问权限]",
        "完全访问权限",
        "[完全存取權限]",
        "完全存取權限",
        "master",
        "mock",
    }:
        return {key: True for key in PART_PERMISSION_KEYS}

    result = empty_part_permissions()

    def grant(group: str, module: str, *actions: str) -> None:
        for action in actions:
            key = permission_key(group, module, action)
            if key in PART_PERMISSION_KEY_SET:
                result[key] = True

    if normalized in {
        "採購助理_一般權限".casefold(),
        "採購助理_信任權限".casefold(),
        "採購助理樣品_信任權限".casefold(),
    }:
        trusted = "信任" in privilege_set
        for module in (
            "overview",
            "suppliers",
            "replenishment",
            "purchaseHistory",
            "inventoryReference",
            "specReference",
            "associations",
            "files",
        ):
            grant("procurement", module, "read")
        grant("procurement", "overview", "update")
        grant("procurement", "suppliers", "update")
        grant("procurement", "quotations", "read", "create", "update", "submit", "upload")
        grant("procurement", "cost", "read")
        grant("procurement", "replenishment", "update")
        grant("procurement", "purchaseHistory", "create")
        grant("procurement", "files", "upload")
        if trusted:
            for module in ("quotations", "cost", "replenishment"):
                grant("procurement", module, "approve")
            grant("procurement", "quotations", "downloadOriginal", "export")
            grant("procurement", "cost", "update", "submit", "export")
            grant("procurement", "purchaseHistory", "export")
            grant("procurement", "specReference", "downloadOriginal")
            grant("procurement", "associations", "link")
            grant("procurement", "files", "downloadOriginal", "export")

    if normalized in {"業務部".casefold(), "業務經理".casefold()}:
        manager = normalized == "業務經理".casefold()
        for module in (
            "overview",
            "customerNaming",
            "packaging",
            "salesPrice",
            "productLinks",
            "notes",
            "customerFiles",
            "processReference",
            "stockReference",
        ):
            grant("business", module, "read")
        grant("business", "overview", "update")
        grant("business", "customerNaming", "update", "submit")
        grant("business", "packaging", "update", "submit", "upload")
        grant("business", "productLinks", "link")
        grant("business", "notes", "update")
        grant("business", "customerFiles", "upload")
        if manager:
            for module in ("overview", "customerNaming", "packaging", "productLinks"):
                grant("business", module, "approve")
            grant("business", "packaging", "downloadOriginal", "export")
            grant("business", "productLinks", "bulkUpdate")
            grant("business", "notes", "export")
            grant("business", "customerFiles", "downloadOriginal", "export")
            grant("business", "processReference", "export")
            grant("business", "stockReference", "export")

    if normalized in {"設計部".casefold(), "設計部_只讀".casefold()}:
        editable = normalized == "設計部".casefold()
        for module in (
            "overview",
            "drawings2d",
            "models3d",
            "materialSpec",
            "dimensions",
            "process",
            "changeRequests",
            "associations",
            "referenceFiles",
        ):
            grant("design", module, "read")
        if editable:
            grant("design", "overview", "update")
            for module in ("drawings2d", "models3d"):
                grant("design", module, "upload", "downloadOriginal", "submit")
            for module in ("materialSpec", "dimensions", "process"):
                grant("design", module, "update", "submit")
            grant("design", "changeRequests", "create", "update", "submit", "upload")
            grant("design", "associations", "link", "submit")
            grant("design", "referenceFiles", "upload", "downloadOriginal")

    if normalized in {
        "品檢員".casefold(),
        "品檢主管".casefold(),
        "品檢包裝主管".casefold(),
        "品檢包裝主管excel".casefold(),
        "包裝員".casefold(),
        "包裝員2部".casefold(),
    }:
        supervisor = normalized in {
            "品檢主管".casefold(),
            "品檢包裝主管".casefold(),
            "品檢包裝主管excel".casefold(),
        }
        packaging = normalized in {
            "品檢包裝主管".casefold(),
            "品檢包裝主管excel".casefold(),
            "包裝員".casefold(),
            "包裝員2部".casefold(),
        }
        excel = normalized == "品檢包裝主管excel".casefold()
        for module in (
            "overview",
            "standards",
            "dimensions",
            "process",
            "inspectionResults",
            "inspectionFiles",
            "specialAcceptance",
            "designChangeReference",
            "bomReference",
            "laserReference",
        ):
            grant("quality", module, "read")
        if normalized not in {"包裝員".casefold(), "包裝員2部".casefold()}:
            grant("quality", "inspectionResults", "create", "update", "submit")
            grant("quality", "inspectionFiles", "upload")
            grant("quality", "specialAcceptance", "create", "submit", "upload")
        if packaging:
            grant(
                "quality",
                "packagingExecution",
                "read",
                "create",
                "update",
                "submit",
                "upload",
            )
        if supervisor:
            for module in (
                "standards",
                "dimensions",
                "process",
                "inspectionResults",
                "specialAcceptance",
                "packagingExecution",
            ):
                grant("quality", module, "approve")
            grant("quality", "standards", "update", "submit", "publish")
            grant("quality", "dimensions", "update", "submit", "publish")
            grant("quality", "process", "update", "submit")
            grant("quality", "inspectionFiles", "downloadOriginal")
            grant("quality", "designChangeReference", "downloadOriginal")
            grant("quality", "laserReference", "downloadOriginal")
        if excel:
            for module in (
                "inspectionResults",
                "inspectionFiles",
                "specialAcceptance",
                "designChangeReference",
                "bomReference",
                "laserReference",
                "packagingExecution",
            ):
                grant("quality", module, "export")
            grant("quality", "inspectionFiles", "bulkUpdate")

    if normalized in {"倉庫_組員".casefold(), "倉庫_組長".casefold()}:
        leader = normalized == "倉庫_組長".casefold()
        for module in (
            "overview",
            "locations",
            "receiving",
            "issuing",
            "transactions",
            "stocktake",
            "adjustment",
            "shortage",
            "labels",
            "associations",
            "referenceFiles",
        ):
            grant("warehouse", module, "read")
        grant("warehouse", "locations", "update")
        grant("warehouse", "receiving", "create", "execute")
        grant("warehouse", "issuing", "create", "execute")
        grant("warehouse", "stocktake", "create", "update", "submit")
        grant("warehouse", "adjustment", "create", "submit")
        grant("warehouse", "labels", "execute")
        if leader:
            grant("warehouse", "overview", "export")
            grant("warehouse", "locations", "approve", "bulkUpdate")
            for module in ("receiving", "issuing"):
                grant("warehouse", module, "reverse", "export")
            grant("warehouse", "transactions", "export")
            grant("warehouse", "stocktake", "approve", "export", "bulkUpdate")
            grant("warehouse", "adjustment", "approve", "execute", "reverse")
            grant("warehouse", "shortage", "export")
            grant("warehouse", "labels", "bulkUpdate")
            grant("warehouse", "associations", "link", "bulkUpdate")
            grant("warehouse", "referenceFiles", "downloadOriginal")

    if normalized == "laser":
        for module in (
            "overview",
            "parameters",
            "artwork",
            "outputFiles",
            "photos",
            "fixtures",
            "labels",
            "qualityReference",
            "versionHistory",
        ):
            grant("laser", module, "read")
        grant("laser", "parameters", "update", "submit")
        grant("laser", "artwork", "upload", "downloadOriginal", "submit")
        grant("laser", "outputFiles", "upload", "downloadOriginal", "submit")
        grant("laser", "photos", "upload")
        grant("laser", "fixtures", "update", "upload")
        grant("laser", "labels", "execute")

    return result


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}
