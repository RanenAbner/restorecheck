"""Generate docs/architecture.drawio: the architecture diagram with official AWS icons.

    python scripts/make_diagram.py

Open the result at https://app.diagrams.net (light appearance) and export it as PNG.
Layout rule: no connector crosses a label. Icons whose arrows leave downwards get
their label above, and the results bus runs in its own lane outside the VPC.
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture.drawio"

CATEGORY = {"app": "#E7157B", "compute": "#ED7100", "db": "#C925D1", "storage": "#7AA116",
            "mgmt": "#E7157B", "security": "#DD344C"}
DARK = "#232F3E"
cells, edges = [], []


def icon(cid, res, cat, x, y, label, above=False, size=64):
    pos = ("verticalLabelPosition=top;verticalAlign=bottom;" if above
           else "verticalLabelPosition=bottom;verticalAlign=top;")
    style = (f"sketch=0;outlineConnect=0;fontColor={DARK};gradientColor=none;fillColor={CATEGORY[cat]};"
             "strokeColor=#ffffff;dashed=0;" + pos + "align=center;html=1;fontSize=12;fontStyle=0;aspect=fixed;"
             f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};")
    cells.append((cid, label, style, x, y, size, size))


def group(cid, label, x, y, w, h, kind):
    styles = {
        "cloud": f"shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor={DARK};fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor={DARK};dashed=0;",
        "region": "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;strokeColor=#00A4A6;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=1;",
        "vpc": "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;strokeColor=#8C4FFF;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#8C4FFF;dashed=0;",
        "sg": "rounded=0;fillColor=none;strokeColor=#DD3522;dashed=1;verticalAlign=bottom;align=left;spacingLeft=6;spacingBottom=4;fontColor=#DD3522;fontSize=11;",
        "box": f"rounded=1;arcSize=10;fillColor=#FFFFFF;strokeColor={DARK};align=center;verticalAlign=middle;fontSize=12;fontColor={DARK};",
    }
    cells.append((cid, label, styles[kind] + "html=1;whiteSpace=wrap;fontStyle=0;", x, y, w, h))


def edge(cid, src, dst, label="", exit=None, entry=None, points=()):
    style = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;strokeColor=#545B64;"
             f"strokeWidth=1.5;fontSize=11;fontColor={DARK};labelBackgroundColor=#FFFFFF;")
    if exit:
        style += f"exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;"
    if entry:
        style += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    edges.append((cid, label, style, src, dst, points))


# boundaries
group("cloud", "AWS Cloud", 20, 20, 1420, 800, "cloud")
group("region", "Region: Asia Pacific (Sydney) ap-southeast-2", 40, 60, 1380, 740, "region")
group("vpc", "Default VPC", 260, 330, 700, 450, "vpc")
group("sg_checker", "Checker security group", 280, 380, 220, 200, "sg")
group("sg_temp", "Restored-DB security group (5432 from checker only)", 580, 380, 340, 200, "sg")

# orchestration: labels above the two icons whose arrows go straight down
icon("eb", "eventbridge", "app", 90, 130, "<b>Amazon EventBridge</b><br>cron schedule")
icon("sfn", "step_functions", "app", 330, 130, "<b>AWS Step Functions</b><br>verification workflow", above=True)
icon("verifier", "lambda", "compute", 640, 130, "<b>Verifier Lambda</b><br>prepare · poll · teardown · record", above=True)

# VPC contents: centres line up with the arrows coming down from above
icon("checker", "lambda", "compute", 330, 425, "<b>Checker Lambda</b><br>SQL integrity checks")
icon("temp", "rds", "db", 640, 425, "<b>Temporary RDS instance</b><br>restorecheck-tmp-*")
icon("source", "rds", "db", 330, 650, "<b>Source RDS PostgreSQL</b><br>the database being protected")
icon("snap", "backup", "storage", 640, 650, "<b>RDS snapshots</b><br>newest one restored for the test")

# results column
icon("ddb", "dynamodb", "db", 1080, 110, "<b>Amazon DynamoDB</b><br>pass/fail history")
icon("s3", "s3", "storage", 1080, 250, "<b>Amazon S3</b><br>detailed JSON reports")
icon("cw", "cloudwatch_2", "mgmt", 1080, 390, "<b>Amazon CloudWatch</b><br>metrics, RTO dashboard, logs")
icon("sns", "sns", "app", 1080, 530, "<b>Amazon SNS</b><br>alerts on FAILED / ERROR")
group("email", "Email to the team", 1260, 542, 140, 40, "box")

# cross-cutting
icon("iam", "identity_and_access_management", "security", 90, 400,
     "<b>AWS IAM</b><br>2 least-privilege roles,<br>custom JSON policies,<br>IAM DB authentication")
icon("cfn", "cloudformation", "mgmt", 90, 640, "<b>AWS SAM / CloudFormation</b><br>whole stack as code")

# flow
edge("e1", "eb", "sfn", "1. start run")
edge("e2", "sfn", "verifier", "2. call each step")
edge("e3", "verifier", "temp", "3. restore newest snapshot<br>6. delete (always)", exit=(0.5, 1), entry=(0.5, 0))
edge("e4", "sfn", "checker", "4. run checks", exit=(0.5, 1), entry=(0.5, 0))
edge("e5", "checker", "temp", "5. SQL over TLS,<br>IAM auth token", exit=(1, 0.5), entry=(0, 0.5))
edge("e6", "source", "snap", "daily + manual backups", exit=(1, 0.5), entry=(0, 0.5))
# snapshot -> temporary copy: round the right-hand side, clear of the instance label
edge("e7", "snap", "temp", "", exit=(1, 0.5), entry=(1, 0.5), points=((880, 682), (880, 457)))
# results bus in its own lane between the VPC (ends x=960) and the result icons (x=1080)
BUS = 1020
edge("e8", "verifier", "ddb", "7. record", exit=(1, 0.5), entry=(0, 0.5), points=((BUS, 162), (BUS, 142)))
edge("e9", "verifier", "s3", "", exit=(1, 0.5), entry=(0, 0.5), points=((BUS, 162), (BUS, 282)))
edge("e10", "verifier", "cw", "", exit=(1, 0.5), entry=(0, 0.5), points=((BUS, 162), (BUS, 422)))
edge("e11", "verifier", "sns", "", exit=(1, 0.5), entry=(0, 0.5), points=((BUS, 162), (BUS, 562)))
edge("e12", "sns", "email", "", exit=(1, 0.5), entry=(0, 0.5))


def main():
    q = {chr(34): "&quot;"}
    parts = ['<mxGraphModel dx="1440" dy="840" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
             'arrows="1" fold="1" page="1" pageScale="1" pageWidth="1460" pageHeight="840" math="0" shadow="0">',
             "<root>", '<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for cid, label, style, x, y, w, h in cells:
        parts.append(f'<mxCell id="{cid}" value="{escape(label, q)}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    for cid, label, style, src, dst, points in edges:
        pts = ""
        if points:
            pts = '<Array as="points">' + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points) + "</Array>"
        parts.append(f'<mxCell id="{cid}" value="{escape(label, q)}" style="{style}" edge="1" parent="1" '
                     f'source="{src}" target="{dst}"><mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>')
    parts += ["</root>", "</mxGraphModel>"]
    OUT.write_text('<mxfile host="RestoreCheck"><diagram id="architecture" name="RestoreCheck architecture">'
                   + "".join(parts) + "</diagram></mxfile>\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
