"""Build the static results page (docs/index.html) from results/scenarios.json.

    python scripts/build_site.py

GitHub Pages serves docs/ as the project's demo site. The page is a snapshot of
recorded runs, not a live view: re-run scripts/run_scenarios.py and this script
to refresh it.
"""
import html
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "scenarios.json"
OUT = ROOT / "docs" / "index.html"
REPO_URL = "https://github.com/RanenAbner/restorecheck"

CHECKS = [
    ("instance_available", "The restore produced a usable instance of the right engine"),
    ("connect", "The restored database is reachable and login works (IAM token over TLS)"),
    ("tables_present", "Every expected table exists"),
    ("row_counts", "Each table has at least its expected number of rows"),
    ("canary_checksum", "A known table's content matches byte-for-byte"),
    ("test_queries", "Application-level queries hold, e.g. no orphaned rows"),
]

STEPS = [
    ("Schedule", "EventBridge starts a run (nightly, or on demand)"),
    ("Restore", "The newest RDS snapshot is restored into a temporary instance"),
    ("Wait", "Step Functions polls until the copy is available, with no Lambda time limit"),
    ("Verify", "A Lambda inside the VPC logs in with an IAM token and runs the checks"),
    ("Tear down", "The temporary instance is deleted on every path, including failures"),
    ("Record and alert", "Report to S3, history to DynamoDB, metrics to CloudWatch, email via SNS"),
]

STATUS_CLASS = {"PASSED": "pass", "FAILED": "fail", "ERROR": "error"}


def esc(value):
    return html.escape(str(value), quote=True)


def stats(rows):
    restores = [r["restore_seconds"] for r in rows if r.get("restore_seconds")]
    restored = [r for r in rows if r["teardown_ok"] is not None]
    return {
        "correct": sum(r["as_expected"] for r in rows),
        "total": len(rows),
        "median_restore_min": statistics.median(restores) / 60 if restores else None,
        "teardowns_ok": sum(r["teardown_ok"] is True for r in restored),
        "teardowns": len(restored),
    }


def scenario_rows(rows):
    out = []
    for r in rows:
        failed = ", ".join(f"<code>{esc(c)}</code>" for c in r["failed_checks"])
        if r["actual"] == "ERROR":
            failed = esc(r.get("error") or "pipeline error")
        elif not failed:
            failed = "none"
        restore = f"{r['restore_seconds'] / 60:.1f} min" if r.get("restore_seconds") else "–"
        teardown = {True: "deleted", False: "NOT deleted", None: "nothing created"}[r["teardown_ok"]]
        verdict = "as expected" if r["as_expected"] else "UNEXPECTED"
        out.append(
            f"""<tr>
  <td><strong>{esc(r['scenario'])}</strong><br><span class="muted">{esc(r['demonstrates'])}</span></td>
  <td>{esc(r['expected'])}</td>
  <td><span class="badge {STATUS_CLASS.get(r['actual'], 'error')}">{esc(r['actual'])}</span>
      <span class="muted small">{verdict}</span></td>
  <td>{failed}</td>
  <td>{restore}</td>
  <td>{teardown}</td>
</tr>"""
        )
    return "\n".join(out)


def build(rows, run_date):
    s = stats(rows)
    median = f"{s['median_restore_min']:.1f}" if s["median_restore_min"] else "–"
    steps = "\n".join(
        f'<li><span class="step-no">{i}</span><div><strong>{esc(t)}</strong><p>{esc(d)}</p></div></li>'
        for i, (t, d) in enumerate(STEPS, 1)
    )
    checks = "\n".join(f"<tr><td><code>{esc(n)}</code></td><td>{esc(d)}</td></tr>" for n, d in CHECKS)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RestoreCheck Results</title>
<meta name="description" content="Automated backup recoverability verification on AWS: results from real test restores.">
<style>
  :root {{
    --bg: #ffffff; --fg: #1b1f24; --muted: #5b6470; --line: #d9dee4; --card: #f6f8fa;
    --accent: #0b6bcb; --pass: #1a7f37; --fail: #c4321b; --error: #8a5a00;
    --pass-bg: #dcf5e3; --fail-bg: #fde4df; --error-bg: #fff1cc;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f1419; --fg: #e6e9ed; --muted: #9aa4af; --line: #2c343d; --card: #161c23;
      --accent: #5aa9ff; --pass: #4cc76d; --fail: #ff7a63; --error: #f0b94a;
      --pass-bg: #123a21; --fail-bg: #45201a; --error-bg: #3b2f12;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--fg);
         font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
  main {{ max-width: 1040px; margin: 0 auto; padding: 32px 16px 64px; }}
  h1 {{ font-size: 2.2rem; margin: 0 0 4px; letter-spacing: -0.02em; }}
  h2 {{ font-size: 1.3rem; margin: 48px 0 12px; }}
  p {{ margin: 0 0 12px; }}
  a {{ color: var(--accent); }}
  code {{ font: 0.88em ui-monospace, SFMono-Regular, Consolas, monospace;
          background: var(--card); border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px; }}
  .tagline {{ color: var(--muted); font-size: 1.1rem; margin-bottom: 20px; }}
  .lede {{ font-size: 1.05rem; max-width: 760px; }}
  .note {{ border-left: 3px solid var(--accent); background: var(--card); padding: 10px 14px;
           border-radius: 0 6px 6px 0; color: var(--muted); font-size: 0.93rem; margin: 20px 0; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 24px; }}
  .stat {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px; }}
  .stat .value {{ font-size: 1.9rem; font-weight: 700; }}
  .stat .label {{ color: var(--muted); font-size: 0.9rem; }}
  ol.steps {{ list-style: none; padding: 0; margin: 0; display: grid;
              grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
  ol.steps li {{ display: flex; gap: 10px; background: var(--card); border: 1px solid var(--line);
                 border-radius: 10px; padding: 12px; }}
  ol.steps p {{ margin: 2px 0 0; color: var(--muted); font-size: 0.88rem; }}
  .step-no {{ flex: none; width: 26px; height: 26px; border-radius: 50%; background: var(--accent);
              color: var(--bg); display: grid; place-items: center; font-weight: 700; font-size: 0.9rem; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; min-width: 640px; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  th {{ background: var(--card); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }}
  tr:last-child td {{ border-bottom: none; }}
  .muted {{ color: var(--muted); }}
  .small {{ font-size: 0.82rem; }}
  .badge {{ display: inline-block; font-weight: 700; font-size: 0.82rem; padding: 2px 8px; border-radius: 999px; }}
  .badge.pass {{ color: var(--pass); background: var(--pass-bg); }}
  .badge.fail {{ color: var(--fail); background: var(--fail-bg); }}
  .badge.error {{ color: var(--error); background: var(--error-bg); }}
  footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--muted); font-size: 0.9rem; }}
</style>
</head>
<body>
<main>
  <h1>RestoreCheck</h1>
  <p class="tagline">Automated backup recoverability verification on AWS</p>
  <p class="lede">Cloud storage keeps backups <em>durable</em>: the bytes are not lost. It does not prove they are
  <em>recoverable</em>. A backup can be complete on disk yet missing a table, silently corrupted, or encrypted with a
  key that no longer works. RestoreCheck proves recoverability the only way that counts: it regularly restores the
  newest database backup into a temporary copy, checks the data inside it, records the result, alerts on failure,
  and always deletes the copy.</p>

  <div class="stats">
    <div class="stat"><div class="value">{s['correct']}/{s['total']}</div><div class="label">scenarios classified correctly</div></div>
    <div class="stat"><div class="value">{median} min</div><div class="label">median restore time (RTO)</div></div>
    <div class="stat"><div class="value">{s['teardowns_ok']}/{s['teardowns']}</div><div class="label">temporary copies deleted</div></div>
    <div class="stat"><div class="value">{len(CHECKS)}</div><div class="label">integrity checks per restore</div></div>
  </div>

  <div class="note">A recorded snapshot, not a live view: results of real runs on AWS (ap-southeast-2, db.t3.micro,
  PostgreSQL 17) on {esc(run_date)}. Restore times are measured to the nearest minute, because the workflow checks
  progress once a minute.</div>

  <h2>How a run works</h2>
  <ol class="steps">
{steps}
  </ol>

  <h2>Results: every kind of damage is caught</h2>
  <p>For each scenario the demo database was reset, damaged in one specific way, and backed up, then RestoreCheck
  verified that backup. A trustworthy verifier must pass the healthy backup and catch every broken one.</p>
  <div class="table-wrap">
  <table>
    <thead><tr><th>Scenario</th><th>Expected</th><th>Result</th><th>Failed checks</th><th>Restore</th><th>Temporary copy</th></tr></thead>
    <tbody>
{scenario_rows(rows)}
    </tbody>
  </table>
  </div>
  <p class="muted small" style="margin-top:10px">The <strong>corrupt-data</strong> row is the key result: one changed value
  leaves every table and row count intact, so only a content checksum can catch it.</p>

  <h2>The integrity checks</h2>
  <div class="table-wrap">
  <table>
    <thead><tr><th>Check</th><th>What it proves</th></tr></thead>
    <tbody>
{checks}
    </tbody>
  </table>
  </div>

  <h2>Built with</h2>
  <p>Amazon EventBridge, AWS Step Functions, AWS Lambda (Python 3.12), Amazon RDS for PostgreSQL, Amazon VPC,
  Amazon DynamoDB, Amazon S3, Amazon SNS, Amazon CloudWatch and AWS IAM, deployed as code with AWS SAM / CloudFormation.
  Each Lambda has its own least-privilege custom IAM policy, and the checker logs in with IAM database
  authentication, so no database password is stored anywhere.</p>

  <footer>
    Source code, templates and full documentation: <a href="{REPO_URL}">{REPO_URL.removeprefix('https://')}</a>
    · <a href="{REPO_URL}/blob/main/docs/references.md">References</a>
    · <a href="{REPO_URL}/blob/main/results/scenarios.md">Raw results</a>
  </footer>
</main>
</body>
</html>
"""


def main():
    rows = json.loads(RESULTS.read_text(encoding="utf-8"))
    run_date = (ROOT / "results" / "scenarios.md").read_text(encoding="utf-8").split(" on ", 1)[1].split(" ", 1)[0]
    OUT.write_text(build(rows, run_date), encoding="utf-8")
    (OUT.parent / ".nojekyll").write_text("", encoding="utf-8")  # serve the HTML as-is
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
