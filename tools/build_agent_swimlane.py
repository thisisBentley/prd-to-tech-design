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
        "subtitle": "Producers create. Consumers accept. Independent reviewers challenge. A deterministic Gatekeeper decides readiness.",
        "human": "HUMAN DECISION OWNER",
        "producers": "PRODUCERS",
        "consumer": "CONSUMER REVIEWERS",
        "independent": "INDEPENDENT REVIEWERS",
        "orchestration": "ORCHESTRATION / GATE",
        "human_title": "Decision Cards & Escalations",
        "human_sub": "business choice · permissions · irreversible risk · unresolved disagreement",
        "discovery": "DISCOVERY",
        "delivery": "DELIVERY",
        "tech": "TECH SOLUTION",
        "discovery_phase": "current state · evidence · decisions",
        "delivery_phase": "product contract",
        "tech_phase": "implementation contract",
        "dp": "Discovery Producer",
        "dp_sub": "problem · current state · evidence · decisions",
        "delp": "Delivery Producer",
        "delp_sub": "PRD · Overview · Prototype · frozen handoff",
        "tp": "Tech Producer",
        "tp_sub": "solution · ledgers · architecture · frozen handoff",
        "dir": "Delivery Intake Reviewer",
        "dir_sub": "sources · decision closure · sufficiency",
        "tpd": "Tech PRD Diagnostician",
        "tpd_sub": "ambiguity · contracts · testability",
        "par": "Product Acceptance Reviewer",
        "par_sub": "scope · permissions · AC inheritance",
        "dr": "Delivery Reviewer + QA Red Team",
        "dr_sub": "roles · actions · enums · exceptions · AC",
        "tr": "Tech Reviewer",
        "tr_sub": "T1 / R1 · BA1 / TA1 / AX1 when triggered",
        "orch": "Orchestrator",
        "orch_sub": "freeze handoff → isolate context → route review → new revision",
        "gate": "Deterministic Gatekeeper",
        "gate_sub": "schemas · hashes · evidence · blockers · decisions",
        "ready": "READY",
        "frozen": "frozen handoff",
        "accepted": "ACCEPTED",
        "review": "review",
        "returned": "RETURNED → producer",
        "blocked": "BLOCKED → Decision Card",
        "legend_producer": "Producer",
        "legend_consumer": "Consumer review",
        "legend_independent": "Independent review",
        "legend_human": "Human decision",
        "legend_gate": "Deterministic gate",
        "discovery_note": "No separate independent reviewer in current MVP;\nDelivery Intake is the first consumer gate.",
        "footnote": "No producer approves its own work. Every review binds to a frozen revision and evidence. Red dashed = return to producer; amber dashed = human decision. Gatekeeper is code, not an LLM.",
    },
    "zh": {
        "title": "受控多智能体研发交付",
        "subtitle": "生产者负责产出，下游消费者负责验收，独立审查者负责挑战，确定性 Gatekeeper 负责最终放行。",
        "human": "人工决策者",
        "producers": "生产者",
        "consumer": "消费者复审",
        "independent": "独立复审",
        "orchestration": "编排与最终守门",
        "human_title": "决策卡与升级事项",
        "human_sub": "业务口径 · 权限范围 · 不可逆风险 · 未解决分歧",
        "discovery": "DISCOVERY",
        "delivery": "DELIVERY",
        "tech": "TECH SOLUTION",
        "discovery_phase": "现状 · 证据 · 决策",
        "delivery_phase": "产品契约",
        "tech_phase": "实现契约",
        "dp": "Discovery Producer",
        "dp_sub": "问题 · 现状 · 证据 · 决策",
        "delp": "Delivery Producer",
        "delp_sub": "PRD · Overview · Prototype · 冻结交接",
        "tp": "Tech Producer",
        "tp_sub": "技术方案 · 四本账 · 架构 · 冻结交接",
        "dir": "Delivery Intake Reviewer",
        "dir_sub": "信息源 · 决策关闭 · 充分性",
        "tpd": "Tech PRD Diagnostician",
        "tpd_sub": "歧义 · 契约 · 可测试性",
        "par": "Product Acceptance Reviewer",
        "par_sub": "范围 · 权限 · AC 承接",
        "dr": "Delivery Reviewer + QA Red Team",
        "dr_sub": "角色 · 动作 · 枚举 · 异常 · AC",
        "tr": "Tech Reviewer",
        "tr_sub": "T1 / R1 · 条件触发 BA1 / TA1 / AX1",
        "orch": "Orchestrator",
        "orch_sub": "冻结交接 → 隔离上下文 → 路由复审 → 生成新版本",
        "gate": "Deterministic Gatekeeper",
        "gate_sub": "Schema · 哈希 · 证据 · 阻断项 · 决策",
        "ready": "READY",
        "frozen": "冻结交接",
        "accepted": "ACCEPTED",
        "review": "复审",
        "returned": "RETURNED → 生产者",
        "blocked": "BLOCKED → 决策卡",
        "legend_producer": "生产者",
        "legend_consumer": "消费者复审",
        "legend_independent": "独立复审",
        "legend_human": "人工决策",
        "legend_gate": "确定性门禁",
        "discovery_note": "当前 MVP 未单独设置 Discovery 独立审查者；\nDelivery Intake 是第一个消费者门禁。",
        "footnote": "生产者不能批准自己的产物；每次复审绑定冻结版本与证据；红色虚线 = 退回生产者；琥珀虚线 = 人工决策；Gatekeeper 是程序，不是另一个 LLM。",
    },
}

COLORS = {
    "bg": "#F7F9FC",
    "ink": "#122033",
    "muted": "#61708A",
    "line": "#DCE3EC",
    "human": "#F4A62A",
    "human_bg": "#FFF8E9",
    "producer": "#3378D6",
    "producer_bg": "#EDF5FF",
    "consumer": "#159A83",
    "consumer_bg": "#EAFBF7",
    "independent": "#7557C8",
    "independent_bg": "#F2EEFF",
    "gate": "#3C4A5F",
    "gate_bg": "#EDF1F5",
    "return": "#D85B63",
    "white": "#FFFFFF",
}


def esc(value: str) -> str:
    return escape(value)


def text(x: float, y: float, value: str, size: int = 16, fill: str | None = None,
         weight: int = 400, anchor: str = "start", opacity: float = 1.0) -> str:
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill or COLORS["ink"]}" text-anchor="{anchor}" '
            f'opacity="{opacity}">{esc(value)}</text>')


def pill(x: float, y: float, w: float, h: float, value: str, fill: str, stroke: str,
         size: int = 14, color: str | None = None) -> str:
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>' +
            text(x + w / 2, y + h / 2 + size * 0.35, value, size, color or stroke, 700, "middle"))


def lane(y: float, h: float, label: str, color: str, bg: str) -> str:
    return (
        f'<rect x="40" y="{y}" width="1840" height="{h}" rx="18" fill="{bg}" stroke="{color}" stroke-opacity="0.18"/>'
        f'<rect x="40" y="{y}" width="205" height="{h}" rx="18" fill="{color}" fill-opacity="0.08"/>'
        f'<rect x="235" y="{y}" width="2" height="{h}" fill="{color}" fill-opacity="0.24"/>'
        + text(62, y + h / 2 - 2, label, 13 if len(label) > 18 else 14, color, 800)
    )


def card(x: float, y: float, w: float, h: float, title: str, subtitle: str,
         color: str, bg: str, step: str | None = None) -> str:
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{COLORS["white"]}" stroke="{color}" stroke-opacity="0.34" filter="url(#shadow)"/>',
        f'<rect x="{x}" y="{y}" width="8" height="{h}" rx="4" fill="{color}"/>',
        text(x + 24, y + 34, title, 17, COLORS["ink"], 750),
        text(x + 24, y + 60, subtitle, 13, COLORS["muted"], 450),
    ]
    if step:
        out.append(pill(x + w - 50, y + 14, 34, 26, step, COLORS["white"], color, 13, color))
    return "".join(out)


def path(d: str, color: str, width: float = 2.4, dashed: bool = False,
         marker: str = "arrow-flow", opacity: float = 1.0) -> str:
    dash = ' stroke-dasharray="9 7"' if dashed else ""
    return (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round" stroke-opacity="{opacity}"{dash} '
            f'marker-end="url(#{marker})"/>')


def build(lang: str) -> str:
    c = COPY[lang]
    out: list[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">')
    out.append(f'<title id="title">{esc(c["title"])}</title>')
    out.append(f'<desc id="desc">{esc(c["subtitle"])}</desc>')
    out.append('<defs>')
    out.append('<filter id="shadow" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#18324D" flood-opacity="0.10"/></filter>')
    for name, color in [("arrow-flow", COLORS["producer"]), ("arrow-consumer", COLORS["consumer"]), ("arrow-independent", COLORS["independent"]), ("arrow-return", COLORS["return"]), ("arrow-gate", COLORS["gate"])]:
        out.append(f'<marker id="{name}" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L10,5 L0,10 Z" fill="{color}"/></marker>')
    out.append('</defs>')
    out.append(f'<rect width="{W}" height="{H}" fill="{COLORS["bg"]}"/>')
    out.append(f'<rect x="0" y="0" width="{W}" height="132" fill="{COLORS["white"]}"/>')
    out.append(f'<rect x="0" y="130" width="{W}" height="2" fill="{COLORS["line"]}"/>')
    out.append(text(64, 66, c["title"], 40, COLORS["ink"], 800))
    out.append(text(64, 101, c["subtitle"], 17, COLORS["muted"], 450))
    # legend
    legend_items = [
        (c["legend_producer"], COLORS["producer"]),
        (c["legend_consumer"], COLORS["consumer"]),
        (c["legend_independent"], COLORS["independent"]),
        (c["legend_human"], COLORS["human"]),
        (c["legend_gate"], COLORS["gate"]),
    ]
    lx = 1270
    for idx, (label, color) in enumerate(legend_items):
        yy = 50 + (idx // 3) * 32
        xx = lx + (idx % 3) * 205
        out.append(f'<circle cx="{xx}" cy="{yy}" r="6" fill="{color}"/>')
        out.append(text(xx + 13, yy + 5, label, 13, COLORS["muted"], 650))
    # stage header
    headers = [
        (260, 380, c["discovery"], c["discovery_phase"], COLORS["producer"]),
        (640, 600, c["delivery"], c["delivery_phase"], COLORS["producer"]),
        (1240, 630, c["tech"], c["tech_phase"], COLORS["producer"]),
    ]
    for x, w, title, sub, color in headers:
        out.append(f'<rect x="{x+8}" y="150" width="{w-16}" height="58" rx="14" fill="{color}" fill-opacity="0.08"/>')
        out.append(text(x + 28, 176, title, 15, color, 850))
        out.append(text(x + 28, 197, sub, 12, COLORS["muted"], 500))
    for x in (640, 1240):
        out.append(f'<line x1="{x}" y1="218" x2="{x}" y2="1010" stroke="{COLORS["line"]}" stroke-width="2"/>')
    # lanes
    out.append(lane(220, 90, c["human"], COLORS["human"], COLORS["human_bg"]))
    out.append(lane(330, 160, c["producers"], COLORS["producer"], COLORS["producer_bg"]))
    out.append(lane(510, 160, c["consumer"], COLORS["consumer"], COLORS["consumer_bg"]))
    out.append(lane(690, 160, c["independent"], COLORS["independent"], COLORS["independent_bg"]))
    out.append(lane(870, 150, c["orchestration"], COLORS["gate"], COLORS["gate_bg"]))
    # human card
    out.append(card(640, 239, 760, 54, c["human_title"], c["human_sub"], COLORS["human"], COLORS["human_bg"]))
    # producer cards
    out.append(card(285, 365, 330, 92, c["dp"], c["dp_sub"], COLORS["producer"], COLORS["producer_bg"], "1"))
    out.append(card(675, 365, 510, 92, c["delp"], c["delp_sub"], COLORS["producer"], COLORS["producer_bg"], "3"))
    out.append(card(1275, 365, 360, 92, c["tp"], c["tp_sub"], COLORS["producer"], COLORS["producer_bg"], "6"))
    # consumer review cards
    out.append(card(285, 545, 330, 92, c["dir"], c["dir_sub"], COLORS["consumer"], COLORS["consumer_bg"], "2"))
    out.append(card(675, 545, 510, 92, c["tpd"], c["tpd_sub"], COLORS["consumer"], COLORS["consumer_bg"], "5"))
    out.append(card(1275, 545, 360, 92, c["par"], c["par_sub"], COLORS["consumer"], COLORS["consumer_bg"], "7"))
    # independent review cards
    out.append(card(675, 725, 510, 92, c["dr"], c["dr_sub"], COLORS["independent"], COLORS["independent_bg"], "4A"))
    out.append(card(1275, 725, 360, 92, c["tr"], c["tr_sub"], COLORS["independent"], COLORS["independent_bg"], "4B"))
    out.append(text(445, 784, c["discovery_note"].split("\n")[0], 12, COLORS["muted"], 550, "middle"))
    out.append(text(445, 803, c["discovery_note"].split("\n")[1], 12, COLORS["muted"], 450, "middle"))
    # orchestration
    out.append(f'<rect x="285" y="905" width="930" height="64" rx="16" fill="{COLORS["white"]}" stroke="{COLORS["gate"]}" stroke-opacity="0.30" filter="url(#shadow)"/>')
    out.append(f'<rect x="285" y="905" width="8" height="64" rx="4" fill="{COLORS["gate"]}"/>')
    out.append(text(310, 932, c["orch"], 17, COLORS["ink"], 750))
    out.append(text(310, 954, c["orch_sub"], 13, COLORS["muted"], 450))
    out.append(f'<rect x="1255" y="900" width="455" height="72" rx="16" fill="{COLORS["white"]}" stroke="{COLORS["gate"]}" stroke-opacity="0.45" filter="url(#shadow)"/>')
    out.append(f'<rect x="1255" y="900" width="8" height="72" rx="4" fill="{COLORS["gate"]}"/>')
    out.append(text(1280, 929, c["gate"], 17, COLORS["ink"], 750))
    out.append(text(1280, 951, c["gate_sub"], 13, COLORS["muted"], 450))
    out.append(pill(1735, 913, 92, 42, c["ready"], "#E9F8F1", "#13966F", 15, "#107653"))
    # flow arrows
    out.append(path("M450 457 L450 537", COLORS["producer"], marker="arrow-flow"))
    out.append(text(463, 498, c["frozen"], 12, COLORS["producer"], 650))
    out.append(path("M615 591 H635 V411 H667", COLORS["consumer"], marker="arrow-consumer"))
    out.append(text(607, 505, c["accepted"], 11, COLORS["consumer"], 700, "middle"))
    out.append(path("M1185 411 H1210 V771 H1185", COLORS["producer"], marker="arrow-independent"))
    out.append(path("M675 771 H650 V591 H667", COLORS["independent"], marker="arrow-consumer"))
    out.append(path("M1185 591 H1225 V411 H1267", COLORS["consumer"], marker="arrow-flow"))
    out.append(path("M1275 411 H1255 V771 H1267", COLORS["producer"], marker="arrow-independent"))
    out.append(path("M1635 771 H1690 V591 H1643", COLORS["independent"], marker="arrow-consumer"))
    out.append(path("M1635 591 H1710 V900", COLORS["consumer"], marker="arrow-gate"))

    out.append(path("M1215 937 H1247", COLORS["gate"], marker="arrow-gate"))
    # return loops
    out.append(path("M285 570 H265 V411 H277", COLORS["return"], 2.1, True, "arrow-return", 0.9))
    out.append(path("M675 770 H658 V500 H667", COLORS["return"], 2.1, True, "arrow-return", 0.9))
    out.append(path("M1275 770 H1250 V500 H1267", COLORS["return"], 2.1, True, "arrow-return", 0.9))
    out.append(text(268, 635, c["returned"], 11, COLORS["return"], 650, "start"))
    # human decision dashed relationship
    out.append(path("M1400 293 V320 H1200 V900", COLORS["human"], 2.0, True, "arrow-gate", 0.8))
    out.append(text(1208, 850, c["blocked"], 11, COLORS["human"], 650))
    # footer
    out.append(f'<rect x="40" y="1035" width="1840" height="26" rx="13" fill="{COLORS["white"]}" stroke="{COLORS["line"]}"/>')
    out.append(text(62, 1053, c["footnote"], 12, COLORS["muted"], 550))
    out.append('</svg>')
    return "".join(out)


def main() -> int:
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
