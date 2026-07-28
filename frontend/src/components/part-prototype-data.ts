export type PrototypePart = {
  id: string;
  partNumber: string;
  systemId: string;
  name: string;
  nameEn: string;
  category: string;
  material: string;
  stock: number;
  safetyStock: number;
  inTransit: number;
  unitPrice: number;
  unit: string;
  auditStatus: "已审核" | "待审核" | "已退回";
  procurementStatus: "正常供应" | "采购中" | "打样中" | "待停用";
  supplier: string;
  supplierCode: string;
  purchaser: string;
  warehouse: string;
  location: string;
  monthUsage: number;
  updatedAt: string;
  photoCount: number;
  drawingCount: number;
  color: string;
};

type PartSeed = [
  partNumber: string,
  name: string,
  nameEn: string,
  category: string,
  material: string,
  color: string
];

const partSeeds: PartSeed[] = [
  ["AL39072-PS", "铝合金转向座总成", "Aluminum steering hub assembly", "CNC 铝件", "6061-T6 铝合金", "Matt Black"],
  ["AL39073-L", "左转向杯", "Left steering knuckle", "CNC 铝件", "7075-T6 铝合金", "Gunmetal"],
  ["AL39074-R", "右转向杯", "Right steering knuckle", "CNC 铝件", "7075-T6 铝合金", "Gunmetal"],
  ["AL39108-BK", "前桥差速器壳", "Front differential housing", "CNC 铝件", "6061-T6 铝合金", "Black"],
  ["AL39121-S", "电机固定座", "Motor mount", "CNC 铝件", "7075-T6 铝合金", "Silver"],
  ["AL39204-RD", "铝合金避震塔", "Aluminum shock tower", "CNC 铝件", "6061-T6 铝合金", "Red"],
  ["AL39218-BK", "电池托盘支架", "Battery tray bracket", "CNC 铝件", "5052 铝合金", "Black"],
  ["AL39301-GY", "伺服机固定座", "Servo mounting bracket", "CNC 铝件", "6061-T6 铝合金", "Gray"],
  ["PL21036-BK", "前保险杠主体", "Front bumper body", "注塑件", "PA6 + GF30", "Black"],
  ["PL21042-GY", "车灯固定架", "Light mounting frame", "注塑件", "PC+ABS", "Dark Gray"],
  ["PL21105-BK", "电池盒上盖", "Battery box cover", "注塑件", "ABS", "Black"],
  ["PL21118-CL", "车灯透明罩", "Clear lamp lens", "注塑件", "透明 PC", "Clear"],
  ["PL21203-RD", "装饰油桶", "Scale fuel can", "注塑件", "PP", "Red"],
  ["PL21220-BK", "车身侧踏板", "Body side step", "注塑件", "PA6", "Black"],
  ["HW10238-M3", "杯头内六角螺丝 M3×8", "Socket head screw M3×8", "五金件", "SCM435 合金钢", "Black Zinc"],
  ["HW10242-M3", "沉头内六角螺丝 M3×12", "Flat head screw M3×12", "五金件", "SCM435 合金钢", "Black Zinc"],
  ["HW10316-5", "法兰轴承 5×11×4", "Flanged bearing 5×11×4", "五金件", "GCr15 轴承钢", "Silver"],
  ["HW10402-M4", "尼龙防松螺母 M4", "Nylon lock nut M4", "五金件", "碳钢", "Black Zinc"],
  ["HW10488-12", "不锈钢传动轴", "Stainless drive shaft", "五金件", "SUS 420", "Silver"],
  ["HW10530-6", "六角轮毂 6 mm", "Wheel hex hub 6 mm", "五金件", "黄铜", "Brass"],
  ["EL52018-R", "红色 LED 灯组", "Red LED light set", "电子件", "LED / 硅胶线", "Red"],
  ["EL52024-W", "白色 LED 灯组", "White LED light set", "电子件", "LED / 硅胶线", "White"],
  ["EL52106-25", "25KG 数字舵机", "25KG digital servo", "电子件", "金属齿 / 铝壳", "Black"],
  ["EL52142-60", "60A 防水电调", "60A waterproof ESC", "电子件", "PCB / 铝散热器", "Black"],
  ["EL52210-RX", "四通道接收机", "4-channel receiver", "电子件", "PCB / ABS", "Black"],
  ["EL52238-SW", "防水电源开关", "Waterproof power switch", "电子件", "硅胶 / 铜线", "Black"],
  ["PK71018-S", "小号 PE 自封袋", "Small PE zipper bag", "包装件", "LDPE", "Clear"],
  ["PK71024-M", "中号珍珠棉袋", "Medium EPE pouch", "包装件", "EPE", "White"],
  ["PK71106-B", "零件内盒", "Parts inner box", "包装件", "350g 白卡纸", "White"],
  ["PK71128-K", "K=K 五层外箱", "K=K master carton", "包装件", "五层瓦楞纸", "Kraft"],
  ["PK71203-LB", "批次追溯标签", "Batch traceability label", "包装件", "铜版纸", "White"],
  ["PK71220-RH", "RoHS 合格贴纸", "RoHS compliance sticker", "包装件", "PET", "Green"],
  ["RU31008-BK", "橡胶防尘套", "Rubber dust boot", "橡胶件", "NBR 70A", "Black"],
  ["RU31016-GY", "底盘缓冲垫", "Chassis cushion pad", "橡胶件", "硅胶 50A", "Gray"],
  ["RU31102-BK", "1.9 寸攀爬轮胎", "1.9 crawler tire", "橡胶件", "软质橡胶", "Black"],
  ["RU31124-BK", "电池防滑垫", "Battery anti-slip pad", "橡胶件", "EPDM", "Black"]
];

const suppliers = [
  ["东莞市精锐五金有限公司", "VN-00438"],
  ["深圳市华铝精工有限公司", "VN-00216"],
  ["东莞市鸿达塑胶制品厂", "VN-00172"],
  ["惠州市恒泰五金有限公司", "VN-00308"],
  ["深圳市星火电子有限公司", "VN-00521"],
  ["佛山市鸿运包装材料厂", "VN-00492"]
] as const;

const purchasers = ["Amy", "Kelly", "Winnie", "Daniel"] as const;
const procurementStatuses: PrototypePart["procurementStatus"][] = ["正常供应", "采购中", "正常供应", "正常供应", "打样中", "正常供应", "待停用"];
const auditStatuses: PrototypePart["auditStatus"][] = ["已审核", "已审核", "已审核", "待审核", "已审核", "已审核", "已退回"];

function warehouseForCategory(category: string): string {
  if (category === "电子件") return "电子仓";
  if (category === "包装件") return "包材仓";
  if (category === "注塑件" || category === "橡胶件") return "塑胶仓";
  return "五金仓";
}

export const prototypeParts: PrototypePart[] = partSeeds.map((seed, index) => {
  const [partNumber, name, nameEn, category, material, color] = seed;
  const supplier = suppliers[index % suppliers.length];
  const safetyStock = 240 + (index % 5) * 120;
  const stock = index % 6 === 0
    ? Math.max(80, safetyStock - 90)
    : 520 + ((index * 173) % 1380);
  const monthUsage = 120 + ((index * 47) % 520);
  return {
    id: `part-${index + 1}`,
    partNumber,
    systemId: `S${64406 + index}`,
    name,
    nameEn,
    category,
    material,
    stock,
    safetyStock,
    inTransit: index % 4 === 0 ? 480 : index % 3 === 0 ? 240 : 0,
    unitPrice: Number((2.6 + ((index * 137) % 2190) / 100).toFixed(2)),
    unit: "PCS",
    auditStatus: auditStatuses[index % auditStatuses.length],
    procurementStatus: procurementStatuses[index % procurementStatuses.length],
    supplier: supplier[0],
    supplierCode: supplier[1],
    purchaser: purchasers[index % purchasers.length],
    warehouse: warehouseForCategory(category),
    location: `${String.fromCharCode(65 + (index % 5))}${(index % 4) + 1}-${String((index % 8) + 1).padStart(2, "0")}-${String((index % 6) + 1).padStart(2, "0")}`,
    monthUsage,
    updatedAt: `2026-07-${String(24 - (index % 12)).padStart(2, "0")} ${String(9 + (index % 8)).padStart(2, "0")}:42`,
    photoCount: 2 + (index % 4),
    drawingCount: 1 + (index % 3),
    color
  };
});

export const defaultPrototypePart = prototypeParts[0];
