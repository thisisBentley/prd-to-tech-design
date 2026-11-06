#!/usr/bin/env python3
"""Generate the README and presentation swimlane diagrams as standalone SVG."""
from __future__ import annotations

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1920, 1080
FONT = "Inter,'SF Pro Display','PingFang SC','Microsoft YaHei',sans-serif"

COPY = {
    "en": {
        "title": "Controlled Multi-Agent Delivery",
        "subtitle": "One delivery track, three producer stages, two review paths and one deterministic release gate.",
        "human_lane": "HUMAN DECISION",
        "producer_lane": "PRODUCERS",
        "consumer_lane": "CONSUMER REVIEW",
        "independent_lane": "INDEPENDENT REVIEW",
        "control_lane": "ORCHESTRATION / GATE",
        "human": "Decision Cards & Escalations",
        "human_sub": "business policy · permissions · irreversible risk · unresolved disagreement",
        "discovery": "DISCOVERY",
        "delivery": "DELIVERY",
        "tech": "TECH SOLUTION",
        "discovery_sub": "current state · evidence · decisions",
        "delivery_sub": "product contract",
        "tech_sub": "implementation contract",
        "dp": "Discovery Producer",
        "dp_sub": "evidence · constraints · decisions",
        "delp": "Delivery Producer",
        "delp_sub": "PRD · Overview · Prototype · frozen handoff",
        "tp": "Tech Producer",
        "tp_sub": "solution · ledgers · architecture · frozen handoff",
        "intake": "Delivery Intake Reviewer",
        "intake_sub": "sources · decision closure · sufficiency",
        "tpd": "Tech PRD Diagnostician",
        "tpd_sub": "ambiguity · contracts · testability",
        "par": "Product Acceptance Reviewer",
        "par_sub": "scope · permissions · AC",
        "dr": "Delivery Reviewer + QA Red Team",
        "dr_sub": "roles · actions · enums · exceptions · AC",
        "tr": "Tech Reviewer",
        "tr_sub": "T1 / R1 · BA1 / TA1 / AX1 when triggered",
        "orchestrator": "Orchestrator",
        "orchestrator_sub": "freeze handoff → isolate context → route review → create new revision",
        "gatekeeper": "Deterministic Gatekeeper",
        "gatekeeper_sub": "evidence · hashes · blockers · decisions · reviewer chain",
        "gate1": "Discovery accepted",
        "gate2": "Delivery reviews accepted",
        "gate3": "Technical acceptance",
        "ready": "READY",
        "frozen": "frozen",
        "accept": "accept",
        "review": "review",
        "returned": "RETURNED",
        "decision": "BLOCKED → decision",
        "legend_producer": "Producer",
        "legend_consumer": "Consumer review",
        "legend_independent": "Independent review",
        "legend_human": "Human decision",
        "legend_gate": "Gate / checkpoint",
        "discovery_note": "MVP note: Discovery has no separate independent reviewer;\nDelivery Intake is its first consumer gate.",
        "footnote": "A checkpoint needs the accepted reviews shown beneath it. RETURNED always goes to that stage's producer. Gatekeeper is code, not an LLM.",
    },
    "zh": {
        "title": "受控多智能体研发交付",
        "subtitle": "一条交付主线，三个生产阶段，两条复审路径，一个确定性发布门禁。",
        "human_lane": "人工决策",
        "producer_lane": "生产者",
        "consumer_lane": "消费者复审",
        "independent_lane": "独立复审",
        "control_lane": "编排 / 守门",
        "human": "决策卡与升级事项",
        "human_sub": "业务口径 · 权限范围 · 不可逆风险 · 未解决分歧",
        "discovery": "DISCOVERY",
        "delivery": "DELIVERY",
        "tech": "TECH SOLUTION",
        "discovery_sub": "现状 · 证据 · 决策",
        "delivery_sub": "产品契约",
        "tech_sub": "实现契约",
        "dp": "Discovery Producer",
        "dp_sub": "问题 · 现状 · 证据 · 决策",
        "delp": "Delivery Producer",
        "delp_sub": "PRD · Overview · Prototype · 冻结交接",
        "tp": "Tech Producer",
        "tp_sub": "技术方案 · 四本账 · 架构 · 冻结交接",
        "intake": "Delivery Intake Reviewer",
        "intake_sub": "信息源 · 决策关闭 · 充分性",
        "tpd": "Tech PRD Diagnostician",
        "tpd_sub": "歧义 · 契约 · 可测试性",
        "par": "Product Acceptance Reviewer",
        "par_sub": "范围 · 权限 · AC 承接",
        "dr": "Delivery Reviewer + QA Red Team",
        "dr_sub": "角色 · 动作 · 枚举 · 异常 · AC",
        "tr": "Tech Reviewer",
        "tr_sub": "T1 / R1 · 条件触发 BA1 / TA1 / AX1",
        "orchestrator": "Orchestrator",
        "orchestrator_sub": "冻结交接 → 隔离上下文 → 路由复审 → 生成新版本",
        "gatekeeper": "Deterministic Gatekeeper",
        "gatekeeper_sub": "证据 · 哈希 · 阻断项 · 决策 · 复审链",
        "gate1": "Discovery 验收通过",
        "gate2": "Delivery 复审通过",
        "gate3": "技术承接验收通过",
        "ready": "READY",
        "frozen": "冻结交接",
        "accept": "通过",
        "review": "复审",
        "returned": "退回",
        "decision": "BLOCKED → 决策卡",
        "legend_producer": "生产者",
        "legend_consumer": "消费者复审",
        "legend_independent": "独立复审",
        "legend_human": "人工决策",
        "legend_gate": "门禁 / 检查点",
        "discovery_note": "当前 MVP：Discovery 未设置单独独立审查者；\nDelivery Intake 是它的第一个消费者门禁。",
        "footnote": "检查点必须收齐其下方所示复审；RETURNED 一律退回该阶段生产者；Gatekeeper 是程序，不是另一个 LLM。",
    },
}

C = {
    "bg": "#F7F9FC", "ink": "#122033", "muted": "#63718A", "line": "#D9E1EB",
    "human": "#E9A42B", "human_bg": "#FFF8E8",
    "producer": "#3378D6", "producer_bg": "#EDF5FF",
    "consumer": "#169A83", "consumer_bg": "#EAFBF7",
    "independent": "#7557C8", "independent_bg": "#F2EEFF",
    "gate": "#425268", "gate_bg": "#EDF1F5",
    "return": "#D85B63", "white": "#FFFFFF", "ready": "#148F69",
}


def text(x, y, value, size=16, fill=None, weight=400, anchor="start", opacity=1.0):
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill or C["ink"]}" text-anchor="{anchor}" opacity="{opacity}">{escape(value)}</text>')


def lane(y, h, label, color, bg, size=14):
    return (
        f'<rect x="40" y="{y}" width="1840" height="{h}" rx="18" fill="{bg}" stroke="{color}" stroke-opacity=".17"/>'
        f'<path d="M245 {y} V{y+h}" stroke="{color}" stroke-width="2" stroke-opacity=".24"/>'
        + text(60, y + h / 2 + 5, label, size, color, 800)
    )


def card(x, y, w, h, title, subtitle, color, step=None, title_size=17):
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{C["white"]}" stroke="{color}" stroke-opacity=".36" filter="url(#shadow)"/>',
        f'<rect x="{x}" y="{y}" width="8" height="{h}" rx="4" fill="{color}"/>',
        text(x + 24, y + 35, title, title_size, C["ink"], 750),
        text(x + 24, y + 61, subtitle, 13, C["muted"], 450),
    ]
    if step:
        out.append(f'<circle cx="{x+w-27}" cy="{y+27}" r="18" fill="{C["white"]}" stroke="{color}" stroke-opacity=".35"/>')
        out.append(text(x + w - 27, y + 32, step, 12, color, 800, "middle"))
    return "".join(out)


def gate_node(cx, y, code, label):
    w, h = 74, 58
    x = cx - w / 2
    return "".join([
        f'<rect x="{cx-54}" y="{y-38}" width="108" height="22" rx="11" fill="{C["white"]}" stroke="{C["gate"]}" stroke-opacity=".25"/>',
        text(cx, y - 23, label, 10, C["gate"], 700, "middle"),
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{C["gate"]}" filter="url(#shadow)"/>',
        f'<circle cx="{cx}" cy="{y+22}" r="12" fill="{C["white"]}" fill-opacity=".15"/>',
        f'<path d="M{cx-5} {y+22} l3 4 l7 -8" fill="none" stroke="{C["white"]}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
        text(cx, y + 48, code, 10, C["white"], 750, "middle"),
    ])


def path(d, color, width=2.4, dashed=False, marker="arrow-flow", opacity=1.0):
    dash = ' stroke-dasharray="8 7"' if dashed else ""
    return (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
            f'stroke-linejoin="round" stroke-opacity="{opacity}"{dash} marker-end="url(#{marker})"/>')


def build(lang):
    c = COPY[lang]
    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">')
    out.append(f'<title id="title">{escape(c["title"])}</title>')
    out.append(f'<desc id="desc">{escape(c["subtitle"])}</desc>')
    out.append('<defs><filter id="shadow" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#18324D" flood-opacity=".10"/></filter>')
    for name, color in [("arrow-flow", C["producer"]), ("arrow-consumer", C["consumer"]), ("arrow-independent", C["independent"]), ("arrow-return", C["return"]), ("arrow-human", C["human"]), ("arrow-gate", C["gate"])]:
        out.append(f'<marker id="{name}" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L10,5 L0,10 Z" fill="{color}"/></marker>')
    out.append('</defs>')
    out.append(f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>')
    out.append(f'<rect x="0" y="0" width="{W}" height="120" fill="{C["white"]}"/>')
    out.append(text(62, 63, c["title"], 40, C["ink"], 800))
    out.append(text(62, 99, c["subtitle"], 17, C["muted"], 450))
    # legend
    legend = [(c["legend_producer"], C["producer"]), (c["legend_consumer"], C["consumer"]), (c["legend_independent"], C["independent"]), (c["legend_human"], C["human"]), (c["legend_gate"], C["gate"])]
    for i, (label, color) in enumerate(legend):
        x = 1130 + (i % 3) * 220
        y = 48 + (i // 3) * 34
        out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{color}"/>')
        out.append(text(x + 14, y + 5, label, 13, C["muted"], 650))
    # stage headers
    stages = [(260, 380, c["discovery"], c["discovery_sub"]), (640, 600, c["delivery"], c["delivery_sub"]), (1240, 620, c["tech"], c["tech_sub"])]
    for x, w, title, sub in stages:
        out.append(f'<rect x="{x+8}" y="138" width="{w-16}" height="50" rx="13" fill="{C["producer"]}" fill-opacity=".07"/>')
        out.append(text(x + 26, 161, title, 14, C["producer"], 850))
        out.append(text(x + 26, 181, sub, 11, C["muted"], 500))
    out.append(f'<path d="M640 200 V1010" stroke="{C["line"]}" stroke-width="2"/>')
    out.append(f'<path d="M1240 200 V1010" stroke="{C["line"]}" stroke-width="2"/>')
    # lanes
    out.append(lane(205, 95, c["human_lane"], C["human"], C["human_bg"]))
    out.append(lane(310, 160, c["producer_lane"], C["producer"], C["producer_bg"]))
    out.append(lane(480, 160, c["consumer_lane"], C["consumer"], C["consumer_bg"]))
    out.append(lane(650, 160, c["independent_lane"], C["independent"], C["independent_bg"], 12))
    out.append(lane(820, 185, c["control_lane"], C["gate"], C["gate_bg"], 13))
    # human
    out.append(card(440, 224, 740, 58, c["human"], c["human_sub"], C["human"]))
    out.append(f'<rect x="1210" y="237" width="245" height="32" rx="16" fill="{C["white"]}" stroke="{C["human"]}" stroke-opacity=".45"/>')
    out.append(text(1332, 258, c["decision"], 12, C["human"], 750, "middle"))
    # main producer track
    out.append(card(285, 345, 300, 100, c["dp"], c["dp_sub"], C["producer"], "1"))
    out.append(card(700, 345, 430, 100, c["delp"], c["delp_sub"], C["producer"], "2"))
    out.append(card(1320, 345, 360, 100, c["tp"], c["tp_sub"], C["producer"], "3"))
    # review cards
    out.append(card(495, 530, 290, 90, c["intake"], c["intake_sub"], C["consumer"], "A", 15))
    out.append(card(1080, 530, 300, 90, c["tpd"], c["tpd_sub"], C["consumer"], "B", 16))
    out.append(card(1495, 530, 345, 90, c["par"], c["par_sub"], C["consumer"], "C", 13))
    out.append(card(760, 700, 460, 90, c["dr"], c["dr_sub"], C["independent"], "D", 17))
    out.append(card(1350, 700, 330, 90, c["tr"], c["tr_sub"], C["independent"], "E", 17))
    out.append(text(445, 744, c["discovery_note"].split("\n")[0], 12, C["muted"], 550, "middle"))
    out.append(text(445, 763, c["discovery_note"].split("\n")[1], 12, C["muted"], 450, "middle"))
    # control lane
    out.append(card(285, 875, 900, 78, c["orchestrator"], c["orchestrator_sub"], C["gate"], None, 18))
    out.append(card(1250, 870, 455, 88, c["gatekeeper"], c["gatekeeper_sub"], C["gate"], None, 18))
    out.append(f'<rect x="1735" y="886" width="98" height="54" rx="27" fill="#EAF9F3" stroke="{C["ready"]}" stroke-width="2"/>')
    out.append(text(1784, 920, c["ready"], 16, C["ready"], 850, "middle"))
    # gates
    out.append(gate_node(640, 357, "R1", c["gate1"]))
    out.append(gate_node(1240, 357, "R2", c["gate2"]))
    out.append(gate_node(1740, 357, "R3", c["gate3"]))
    # main flow
    out.append(path("M585 395 H597", C["producer"], 3, marker="arrow-flow"))
    out.append(path("M683 395 H692", C["producer"], 3, marker="arrow-flow"))
    out.append(path("M1130 395 H1198", C["producer"], 3, marker="arrow-flow"))
    out.append(path("M1282 395 H1312", C["producer"], 3, marker="arrow-flow"))
    out.append(path("M1680 395 H1698", C["producer"], 3, marker="arrow-flow"))
    out.append(path("M1740 415 V860", C["gate"], 2.8, marker="arrow-gate"))
    out.append(path("M1185 914 H1238", C["gate"], 3, marker="arrow-gate"))
    # reviewer acceptance flows back into the checkpoints
    out.append(path("M640 522 V423", C["consumer"], 2.1, True, "arrow-consumer", .9))
    out.append(path("M1150 522 H1180 V423", C["consumer"], 2.1, True, "arrow-consumer", .9))
    out.append(path("M990 692 V645 H1190 V423", C["independent"], 2.1, True, "arrow-independent", .9))
    out.append(path("M1600 522 H1728 V423", C["consumer"], 2.1, True, "arrow-consumer", .9))
    out.append(path("M1515 692 V645 H1705 V423", C["independent"], 2.1, True, "arrow-independent", .9))
    # return paths: a rejected checkpoint returns to its stage producer
    out.append(path("M495 558 H475 V445", C["return"], 2, True, "arrow-return", .95))
    out.append(path("M760 692 V445", C["return"], 2, True, "arrow-return", .95))
    out.append(path("M1080 692 H1055 V445", C["return"], 2, True, "arrow-return", .95))
    out.append(path("M1350 692 H1335 V445", C["return"], 2, True, "arrow-return", .95))
    out.append(path("M1495 558 H1475 V445", C["return"], 2, True, "arrow-return", .95))
    # human control relation: route outside content
    out.append(path("M1180 282 H1870 V826 H1185 V870", C["human"], 2, True, "arrow-human", .9))
    # footer
    out.append(f'<rect x="40" y="1032" width="1840" height="28" rx="14" fill="{C["white"]}" stroke="{C["line"]}"/>')
    out.append(text(62, 1051, c["footnote"], 12, C["muted"], 600))
    out.append('</svg>')
    return "".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for lang, name in [("en", "agent-collaboration-swimlane.svg"), ("zh", "agent-collaboration-swimlane-zh.svg")]:
        path = args.out_dir / name
        path.write_text(build(lang), encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
