// Build the DA-III report (report/RestoreCheck_DA3_Report.docx).
//
//   cd report && npm install && node build_report.js
//
// Section order follows the course's required format. Citations are numbered in
// order of first use (IEEE); the reference texts come from docs/references.md and
// the results table from results/scenarios.json, so the report always matches the
// repository. Team names, the VIT logo and screenshots are placeholders to fill in.
const fs = require("fs");
const path = require("path");
const {
  AlignmentType, BorderStyle, Document, ExternalHyperlink, Footer, Header, HeadingLevel, ImageRun,
  LevelFormat, Packer, PageNumber, Paragraph, Table, TableCell, TableRow,
  TextRun, WidthType,
} = require("docx");

const ROOT = path.resolve(__dirname, "..");
// WITH_FIGURES=1 embeds the screenshots in report/figures/ (git-ignored: they show
// account details) and writes a separate, also git-ignored, file.
const WITH_FIGURES = process.env.WITH_FIGURES === "1";
const FIG_DIR = path.join(__dirname, "figures");
const OUT = path.join(__dirname, WITH_FIGURES ? "RestoreCheck_DA3_Report_with_figures.docx" : "RestoreCheck_DA3_Report.docx");
const TITLE = "RestoreCheck: Automated Backup Recoverability Verification and Disaster-Recovery Testing on AWS";
const REPO = "https://github.com/RanenAbner/restorecheck";
const SITE = "https://ranenabner.github.io/restorecheck/";
const TEAM = [["24BCE1185", "Ranen Abner"], ["24BAI1001", "Sai Charan"]];
const FACULTY = "S. Vigneshwari";
const CITE_AUTHORS = "Ranen Abner, Sai Charan, and S. Vigneshwari"; // team members, then faculty (course format)

// ---------------------------------------------------------------- references
const REFS = {};
for (const line of fs.readFileSync(path.join(ROOT, "docs", "references.md"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\[(\d+)\] (.+)$/);
  if (m) REFS[Number(m[1])] = m[2];
}
const cited = [];
function c(...nums) {
  return nums
    .map((n) => {
      if (!REFS[n]) throw new Error(`No reference [${n}] in docs/references.md`);
      if (!cited.includes(n)) cited.push(n);
      return `[${cited.indexOf(n) + 1}]`;
    })
    .join(", ");
}

const results = JSON.parse(fs.readFileSync(path.join(ROOT, "results", "scenarios.json"), "utf8"));

// ---------------------------------------------------------------- text helpers
const BLACK = "000000";
const LINK = { color: BLACK, underline: {} };
// Inline markup: **bold**, *italic*, `code`, and bare URLs become hyperlinks.
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|https?:\/\/[^\s)]+|doi: 10\.\S+)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), ...base, bold: true }));
    else if (t.startsWith("`")) out.push(new TextRun({ text: t.slice(1, -1), ...base, font: "Consolas", size: 20 }));
    else if (t.startsWith("*")) out.push(new TextRun({ text: t.slice(1, -1), ...base, italics: true }));
    else if (t.startsWith("doi: ")) {
      // Make DOIs clickable: display "doi: 10.x/y", link to https://doi.org/10.x/y
      const doi = t.slice(5).replace(/[.,;:]+$/, "");
      out.push(new TextRun({ text: "doi: ", ...base }));
      out.push(new ExternalHyperlink({ link: `https://doi.org/${doi}`, children: [new TextRun({ text: doi, ...base, ...LINK })] }));
      if (t.length > 5 + doi.length) out.push(new TextRun({ text: t.slice(5 + doi.length), ...base }));
    } else {
      const url = t.replace(/[.,;:]+$/, "");
      out.push(new ExternalHyperlink({ link: url, children: [new TextRun({ text: url, ...base, ...LINK })] }));
      if (t.length > url.length) out.push(new TextRun({ text: t.slice(url.length), ...base }));
    }
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const P = (text, opts = {}) =>
  new Paragraph({ children: runs(text), alignment: AlignmentType.JUSTIFIED, spacing: { after: 140 }, ...opts });
// Numbered section headings (1, 1.1, ...); the title, references and appendix stay unnumbered.
const UNNUMBERED = new Set(["Title", "References"]);
let h1Count = 0;
let h2Count = 0;
const H1 = (text) => {
  let label = text;
  if (!UNNUMBERED.has(text) && !text.startsWith("Appendix")) {
    h1Count += 1;
    h2Count = 0;
    label = `${h1Count}.  ${text}`;
  }
  return new Paragraph({ text: label, heading: HeadingLevel.HEADING_1 });
};
const H2 = (text) => {
  h2Count += 1;
  return new Paragraph({ text: `${h1Count}.${h2Count}  ${text}`, heading: HeadingLevel.HEADING_2 });
};
const bullet = (text) =>
  new Paragraph({ children: runs(text), numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 } });
let listInstance = 0;
const numberedList = (items) => {
  listInstance += 1;
  return items.map(
    (text) =>
      new Paragraph({
        children: runs(text),
        numbering: { reference: "numbers", level: 0, instance: listInstance },
        spacing: { after: 80 },
      }),
  );
};
const centered = (text, base = {}, after = 60) =>
  new Paragraph({ children: runs(text, base), alignment: AlignmentType.CENTER, spacing: { after } });
const caption = (text) =>
  new Paragraph({ children: runs(text, { italics: true, size: 20 }), alignment: AlignmentType.CENTER, spacing: { after: 240 } });

const dashed = { style: BorderStyle.DASHED, size: 6, color: BLACK, space: 10 };
const placeholder = (text) =>
  new Paragraph({
    children: [new TextRun({ text, italics: true })],
    alignment: AlignmentType.CENTER,
    border: { top: dashed, bottom: dashed, left: dashed, right: dashed },
    spacing: { before: 240, after: 120, line: 360 },
  });

const cellBorder = { style: BorderStyle.SINGLE, size: 4, color: BLACK };
function table(widths, header, rows) {
  const row = (cells, isHeader) =>
    new TableRow({
      tableHeader: isHeader,
      cantSplit: true,
      children: cells.map(
        (cell, i) =>
          new TableCell({
            width: { size: widths[i], type: WidthType.DXA },
            borders: { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder },
            margins: { top: 60, bottom: 60, left: 100, right: 100 },
            children: [new Paragraph({ children: runs(String(cell), { size: 20, bold: isHeader }) })],
          }),
      ),
    });
  return new Table({
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: widths,
    rows: [row(header, true), ...rows.map((r) => row(r, false))],
  });
}
const spacer = () => new Paragraph({ children: [], spacing: { after: 120 } });

// Figures: embed the PNGs when WITH_FIGURES=1 and every file exists, otherwise a placeholder.
const MAX_W = 600; // px at 96 dpi = the text width (6.27 in)
const pngSize = (buf) => ({ width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) });
function image(file, maxHeight) {
  const data = fs.readFileSync(path.join(FIG_DIR, file));
  const { width, height } = pngSize(data);
  const scale = Math.min(MAX_W / width, maxHeight / height, 1);
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    keepNext: true,
    spacing: { before: 120, after: 40 },
    children: [new ImageRun({ type: "png", data, transformation: { width: Math.round(width * scale), height: Math.round(height * scale) } })],
  });
}
function logo(file) {
  const data = fs.readFileSync(path.join(FIG_DIR, file));
  const { width, height } = pngSize(data);
  const w = 360;
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new ImageRun({ type: "png", data, transformation: { width: w, height: Math.round((height * w) / width) } })],
  });
}
let figureCount = 0;
function figure(files, text, placeholderText) {
  figureCount += 1;
  const present = WITH_FIGURES && files.every((f) => fs.existsSync(path.join(FIG_DIR, f)));
  const maxHeight = files.length > 1 ? 380 : 620;
  return [
    ...(present ? files.map((f) => image(f, maxHeight)) : [placeholder(placeholderText || `[ Insert screenshot: ${text} ]`)]),
    caption(`Figure ${figureCount}. ${text}`),
  ];
}

// ---------------------------------------------------------------- numbers from results
const restoreMin = results.filter((r) => r.restore_seconds).map((r) => r.restore_seconds / 60);
const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
};
const correct = results.filter((r) => r.as_expected).length;
const created = results.filter((r) => r.teardown_ok !== null);
const deleted = created.filter((r) => r.teardown_ok === true).length;
const fmt1 = (x) => x.toFixed(1);

// ---------------------------------------------------------------- content
const body = [];
const add = (...items) => body.push(...items.flat());

// Title block (course format)
add(
  WITH_FIGURES && fs.existsSync(path.join(FIG_DIR, "fig00_vit_logo.png"))
    ? logo("fig00_vit_logo.png")
    : placeholder("[ Insert the official VIT logo here ]"),
  centered("**School of Computer Science and Engineering**", { size: 26 }, 80),
  centered("**Course code:** BCSE355L     **Course Name:** Cloud Architecture Design", {}, 60),
  centered("**Direct Assessment III**     **Max Marks:** 10", {}, 200),
  centered("**Team members (Reg. No., Name):**", {}, 80),
  table([3000, 6026], ["Registration No.", "Name"], TEAM),
  new Paragraph({ children: runs(`**Faculty:** ${FACULTY}`), alignment: AlignmentType.CENTER, spacing: { before: 160, after: 240 } }),
);

add(H1("Title"), P(`**${TITLE}**`, { alignment: AlignmentType.LEFT }));

add(
  H1("Abstract"),
  P(
    `Cloud storage gives backups extremely high durability: Amazon S3, for example, is designed for 99.999999999% (eleven nines) durability ${c(25)}. ` +
      "Durability, however, only guarantees that stored bytes survive. It does not guarantee that a backup can be restored into a working system. " +
      "In practice restores fail because a backup is incomplete, silently corrupted, encrypted with a key that can no longer be used, or because the restore procedure itself is broken. " +
      `This project presents **RestoreCheck**, a serverless system on AWS that continuously proves backup recoverability. On a schedule, an AWS Step Functions workflow restores the newest Amazon RDS for PostgreSQL snapshot into a temporary, network-isolated database instance, runs six integrity checks against the restored data from a Lambda function inside the VPC, records the result in Amazon DynamoDB with a detailed report in Amazon S3, publishes metrics to Amazon CloudWatch, alerts through Amazon SNS, and deletes the temporary instance on every execution path. ` +
      "The whole system is defined as infrastructure as code with AWS SAM, uses a separate least-privilege custom IAM policy for each function, and logs in to the restored database with IAM database authentication, so no database password is stored. " +
      `In six controlled scenarios on AWS, RestoreCheck passed the healthy backup, detected all four kinds of injected data damage (including a single altered value that left every table and row count intact), reported a missing backup as an error, measured a median restore time of ${fmt1(median(restoreMin))} minutes, and deleted every temporary instance it created.`,
  ),
  P("**Keywords:** backup verification, disaster recovery, recoverability, restore testing, AWS Step Functions, Amazon RDS, serverless, least privilege."),
);

add(
  H1("Problem statement"),
  P(
    `Backups are the last line of defence against hardware failure, operator error, software bugs and ransomware ${c(18, 9)}. ` +
      `Under the AWS shared responsibility model, AWS is responsible for the resilience of the underlying infrastructure, while the customer remains responsible for their data and for being able to recover it ${c(24)}. ` +
      "A cloud backup can therefore be perfectly durable and still be useless. Typical causes are:",
  ),
  bullet("the backup is **incomplete**: a table, database or volume was silently left out (configuration drift);"),
  bullet(`the data was **already corrupted** before or while the backup was taken; silent corruption has been measured in large production storage fleets ${c(5)};`),
  bullet(`the backup is encrypted with a **key that was disabled or deleted**: durably stored, but undecryptable ${c(31)};`),
  bullet("the **restore procedure itself is broken**, or too slow to meet the recovery time objective (RTO);"),
  bullet("backups **fail silently** and nobody notices until they are needed."),
  P(
    `The last point is not hypothetical. In January 2017 GitLab lost about six hours of production database changes after an operator error. Its regular database dumps had been failing silently for some time, the failure emails were never delivered, and the team had to recover from an ad-hoc snapshot, a process that took around 18 hours. Its own post-mortem observes that "nobody was responsible for testing this procedure" ${c(19)}.`,
  ),
  P(
    `Testing restores is standard guidance: the AWS Well-Architected Framework asks teams to perform periodic recovery of data to verify backup integrity and processes ${c(21, 20)}, NIST includes testing in contingency planning ${c(14)} and lists tested backups in the Cybersecurity Framework 2.0 ${c(16)}, and ISO/IEC 27031 covers ICT readiness for business continuity ${c(17)}. ` +
      "Manual restore drills, however, are slow, costly and easy to skip, so they are performed rarely or not at all.",
  ),
  P(
    "**Problem:** design and build an automated, low-cost, secure, cloud-native system that regularly proves that the latest backup of a database can actually be restored and that the restored data is complete and intact; that measures how long the restore takes; that alerts the team when verification fails; and that never leaves temporary resources running.",
  ),
);

add(
  H1("Highlights of the project / Novelty"),
  bullet("**Verifies recoverability, not just durability.** Every run performs a real restore of the newest RDS snapshot and inspects the data inside it, instead of trusting that a backup job reported success."),
  bullet("**Data-level integrity checks.** Six checks cover the instance, connectivity, schema, row counts, a byte-for-byte **canary checksum** and application-level test queries. The checksum catches a single altered value that row counts and schema checks cannot see."),
  bullet("**Guaranteed teardown, enforced structurally.** In the Step Functions workflow every failure is routed to a Teardown step; an automated test walks the workflow graph and fails if any path can end without passing through it. A straggler sweep deletes instances left by interrupted runs, but never one young enough to belong to a run in progress."),
  bullet(`**Survives long restores.** A real RDS restore can outlast Lambda's 15-minute limit ${c(34)}; Step Functions waits between short Lambda steps at no cost ${c(36, 37)}.`),
  bullet(`**Security by design.** Each Lambda has its own custom JSON IAM policy: restore and delete are allowed only on instances named \`restorecheck-tmp-*\`, metrics only in one CloudWatch namespace ${c(44, 45)}. The checker logs in with a 15-minute IAM authentication token over verified TLS, so no database password exists anywhere ${c(32, 33)}. Temporary instances are private and reachable only from the checker's security group ${c(47)}.`),
  bullet(`**No idle networking cost.** Only the checker runs inside the VPC, and it makes no AWS API calls (the login token is computed locally) ${c(35)}, so no NAT gateway or VPC endpoints are needed.`),
  bullet("**Evaluated by failure injection.** A reproducible scenario runner damages the demo database in controlled ways and confirms each kind of damage is caught by the intended check, which tests the verifier itself."),
  bullet(`**Infrastructure as code.** The whole system, including IAM, networking, the workflow and the dashboard, is one AWS SAM template compiled to CloudFormation ${c(48, 49)}.`),
  bullet(`**Sustainable Development Goals.** Resilient digital infrastructure (SDG 9) and stronger disaster recovery for essential services (SDG 11) ${c(55, 56)}.`),
  H2("Related work and prior art"),
  P(
    `Cloud-based disaster recovery has been studied for its economics ${c(2)}, its planning and evaluation ${c(1)}, deployment models ${c(4)} and general approaches ${c(3)}. ` +
      `Replication systems such as Remus provide high availability ${c(10)}, but replication faithfully copies logical errors and deletions, so it does not replace verified backups. ` +
      `Field studies show why verification matters: disks fail far more often than datasheets suggest ${c(6)}, data is silently corrupted inside the storage stack ${c(5)}, cloud systems fail in complex ways ${c(7)}, operator error is a leading cause of outages ${c(9)}, and most catastrophic failures come from incorrect handling of errors that simple tests would have caught ${c(8)}. ` +
      `RestoreCheck applies the idea behind chaos engineering ${c(11, 12)}, proactively exercising failure paths in production, to the recovery path, and follows Google's practice of continuously validating data integrity ${c(13)}.`,
  ),
  P(
    `**AWS Backup restore testing.** AWS offers scheduled restore testing that restores recovery points, measures restore job duration and deletes the restored resources afterwards ${c(27, 26)}. ` +
      "Validating the restored *data*, however, is optional and must be programmed by the customer: AWS's documentation states that validation can be run programmatically but not from the AWS Backup console. " +
      "RestoreCheck supplies exactly that missing layer (data-level checks, a per-run report, run history, alerting and a dashboard) as transparent, open-source infrastructure as code. It complements AWS Backup rather than replacing it, and its checker could serve as the validation step for AWS Backup restore tests in future.",
  ),
);

add(
  H1("Dataset link"),
  P(
    "RestoreCheck uses its own synthetic dataset: a demo shop database (customers, products, orders, order items and a 100-row canary table) generated deterministically by `scripts/demo_data.py`, together with the recorded results of the verification scenarios. " +
      "The exported files (CSV tables, expectations and results, with a README and a CC BY 4.0 licence) are in the repository's `dataset/` folder.",
  ),
  P("**Zenodo DOI:** [to be added after uploading dataset/ to Zenodo]"),
  P(`**Citation:** ${CITE_AUTHORS}, "RestoreCheck demo dataset: synthetic shop database and backup-verification scenario results," Zenodo, 2026, doi: [DOI].`),
);

add(
  H1("Project demo link"),
  P(`**Results site:** ${SITE}`),
  P("**Demo video:** [add the link to the recorded demo]"),
);

add(
  H1("GitHub repository link"),
  P(`**Repository:** ${REPO}`),
  P(`**Citation:** ${CITE_AUTHORS}, "${TITLE}," GitHub repository, 2026. [Online]. Available: ${REPO}`),
);

add(
  H1("Architecture diagram"),
  ...figure(
    ["fig01_architecture.png"],
    "RestoreCheck architecture on AWS (region ap-southeast-2). Numbers match the steps below.",
    "[ Insert Figure 1: export docs/architecture.drawio to PNG at app.diagrams.net (File > Export as > PNG, 200%) ]",
  ),
  P(`A run proceeds as follows (Figure 1). The workflow is defined in the Amazon States Language ${c(38)}.`),
  ...numberedList([
    `**Start.** An Amazon EventBridge schedule (nightly by default) starts a Step Functions execution ${c(39)}; runs can also be started on demand.`,
    `**Prepare.** The verifier Lambda deletes stragglers from earlier runs, finds the newest available snapshot of the source database ${c(28)} and starts restoring it into a temporary instance named \`restorecheck-tmp-<timestamp>\` ${c(29)}, placed in a dedicated subnet group and security group, not publicly accessible, with IAM authentication enabled.`,
    `**Wait.** The workflow waits one minute and asks the verifier for the instance status ${c(30)}, repeating until it is available. Unrecoverable states (for example \`inaccessible-encryption-credentials\`, the unusable-key case) and restores longer than a configurable limit fail immediately.`,
    `**Verify.** The checker Lambda, inside the VPC ${c(35)}, connects to the restored database over TLS with an IAM authentication token and runs the integrity checks ${c(32, 33)}.`,
    "**Teardown.** The verifier deletes the temporary instance. Every failure in steps 2 to 4 is caught and routed here; an instance that cannot be deleted yet is retried for up to about 49 minutes.",
    `**Record.** The verifier writes a JSON report to S3, a history row to DynamoDB ${c(40)}, and metrics to CloudWatch ${c(42)}, and publishes an email alert through SNS when the backup did not pass ${c(41)}. Failed runs end in a red Fail state, so they are visible in the Step Functions console.`,
  ]),
  spacer(),
  table([2500, 6526], ["AWS service", "Role in RestoreCheck"], [
    ["Amazon EventBridge", "Scheduled trigger (cron) for verification runs"],
    ["AWS Step Functions", "Orchestrates prepare → wait/poll → checks → teardown → record; guarantees teardown"],
    ["AWS Lambda (verifier)", "Prepare, poll, teardown and record steps; calls the AWS APIs from outside the VPC"],
    ["AWS Lambda (checker)", "Runs the SQL integrity checks from inside the VPC; makes no AWS API calls"],
    ["Amazon RDS for PostgreSQL", "Source database, its snapshots, and the temporary restored instance"],
    ["Amazon VPC / security groups", "Private path from the checker to the temporary instance only (port 5432)"],
    ["Amazon DynamoDB", "Pass/fail history (key: database, run timestamp)"],
    ["Amazon S3", "Detailed JSON report for every run (encrypted, public access blocked, expires after 90 days)"],
    ["Amazon SNS", "Email alert when a backup fails verification or the pipeline errors"],
    ["Amazon CloudWatch", `Logs, custom metrics and a backup-health dashboard with restore-time (RTO) trends ${c(43)}`],
    ["AWS IAM", "Two least-privilege roles with custom JSON policies; IAM database authentication"],
    ["AWS SAM / CloudFormation", "The entire system as one template (infrastructure as code)"],
  ]),
  caption("Table 1. AWS services used and their roles."),
  H2("Integrity checks"),
  table([2300, 3826, 2900], ["Check", "What it proves", "Catches"], [
    ["`instance_available`", "The restore produced a usable instance of the snapshot's engine", "Broken or wrong restores"],
    ["`connect`", "The database is reachable and the IAM login works over TLS", "Network or authentication breakage"],
    ["`tables_present`", "Every expected table exists", "Tables silently missing from the backup"],
    ["`row_counts`", "Each table has at least its expected number of rows", "Truncated or incomplete data"],
    ["`canary_checksum`", "A known table matches byte-for-byte (MD5)", "Altered or corrupted data"],
    ["`test_queries`", "Application queries hold, e.g. no orphaned rows", "Broken referential integrity"],
  ]),
  caption("Table 2. The six integrity checks run against every restored database."),
  P(
    "Expected tables, minimum row counts and test queries are configured in `src/checks/expectations.json`. A run ends as **PASSED** (all checks passed), **FAILED** (restored, but at least one check failed, or no check ran) or **ERROR** (the pipeline itself failed, for example because no snapshot exists). FAILED and ERROR trigger an alert, as does a failed teardown.",
  ),
  H2("Key design decisions"),
  bullet("**Step Functions instead of one Lambda:** restores routinely take longer than 15 minutes, and the workflow's Catch and Retry rules make the teardown guarantee explicit and testable."),
  bullet("**Two functions, two policies:** the verifier can restore and delete only `restorecheck-tmp-*` instances and write only to this stack's table, bucket and topic; the checker can only attach to the VPC and log in as one read-only database user."),
  bullet("**IAM database authentication:** removes stored credentials entirely and keeps the checker free of AWS API calls, which is what lets it run in the VPC without a NAT gateway."),
  bullet(`**Governance:** the AWS account is locked to one region by an organization service control policy ${c(46)}, a common real-world guardrail that overrides even administrator permissions.`),
);

add(
  H1("Screenshots"),
  P("Screenshots taken from the deployed system on AWS (ap-southeast-2) on 21–22 October 2026."),
  ...[
    [["fig02_cloudformation.png"], "CloudFormation: the deployed restorecheck and restorecheck-demo-db stacks"],
    [["fig03_sfn_passed.png"], "Step Functions: graph view of a PASSED execution, every step green and ending in BackupVerified"],
    [["fig_live_graph.png"], "Step Functions: a run in progress, looping through WaitForRestore and CheckRestoreStatus until the restored instance is available"],
    [["fig04_sfn_failed.png"], "Step Functions: the FAILED corrupt-data execution, ending in the red BackupNotVerified state"],
    [["fig04b_output_run.png", "fig04c_output_checks.png"], "Output of the RunIntegrityChecks step in the corrupt-data run: canary_checksum failed while every other check passed"],
    [["fig05_rds_live.png"], "RDS console during a run: the temporary restorecheck-tmp-* instance beside the source database"],
    [["fig06_alert_email.png"], "The SNS alert email received for the corrupt-data backup, naming the failed check"],
    [["fig07_dynamodb.png"], "DynamoDB: run history with PASSED, FAILED and ERROR runs"],
    [["fig08_s3_report.png"], "S3: the detailed JSON verification report of the corrupt-data run"],
    [["fig09_dashboard.png"], "CloudWatch: the restorecheck-backup-health dashboard over the scenario runs (21 October, UTC). The single verifier Lambda error near 13:00 is the expected \"no snapshot\" error of the no-backup scenario, which is how that ERROR is detected"],
    [["fig10a_verifier_policy.png", "fig10b_verifier_policy.png", "fig10c_verifier_policy.png"], "IAM: the verifier's custom least-privilege JSON policy"],
    [["fig10d_checker_policy.png"], "IAM: the checker's custom JSON policy, allowing database login as one user only"],
    [["fig11_results_site.png"], "The results site on GitHub Pages"],
    [["fig12_tests.png"], "Automated test suite output (pytest): 76 tests passed"],
  ].flatMap(([files, text]) => figure(files, text)),
);

const scenarioRows = results.map((r) => [
  `**${r.scenario}**`,
  r.demonstrates,
  r.expected,
  `**${r.actual}**`,
  r.actual === "ERROR" ? "none (no snapshot to restore)" : r.failed_checks.map((x) => `\`${x}\``).join(", ") || "none",
  r.restore_seconds ? fmt1(r.restore_seconds / 60) : "–",
  r.teardown_ok === true ? "deleted" : r.teardown_ok === false ? "NOT deleted" : "none created",
]);

add(
  H1("Results"),
  P(
    "RestoreCheck was deployed to AWS (region ap-southeast-2) with a demo Amazon RDS for PostgreSQL 17 database on db.t3.micro. For each scenario the database was reset to its healthy state, damaged in one specific way, and snapshotted; RestoreCheck then verified that snapshot. A trustworthy verifier must pass the healthy backup and catch every broken one. All scenarios were run with `scripts/run_scenarios.py`, which records the outcome of each run.",
  ),
  table([1250, 2150, 900, 900, 2020, 900, 906], ["Scenario", "Simulated problem", "Expected", "Actual", "Failed checks", "Restore (min)", "Temporary copy"], scenarioRows),
  caption("Table 3. Outcome of the six verification scenarios on AWS."),
  bullet(`**Accuracy:** ${correct} of ${results.length} scenarios were classified as expected, with no false alarm on the healthy backup.`),
  bullet("**Each kind of damage was caught by the check designed for it.** The most important result is *corrupt-data*: changing one value leaves every table and row count intact, so only the content checksum detects it. A verifier that only counts rows, or only confirms that the restore job succeeded, would have passed this broken backup."),
  bullet(`**Restore time (RTO):** median ${fmt1(median(restoreMin))} minutes (range ${fmt1(Math.min(...restoreMin))}–${fmt1(Math.max(...restoreMin))}) for this database, measured to the nearest minute because the workflow polls once a minute ${c(22)}.`),
  bullet(`**Cost control:** ${deleted} of ${created.length} temporary instances were deleted automatically; the no-backup run created none. Each temporary db.t3.micro instance exists only for the run itself (about 8 minutes) plus the time RDS takes to delete it.`),
  bullet("**Alerting:** every FAILED and ERROR run produced an SNS email with the failed checks and a link to the full report."),
  H2("Engineering verification"),
  P(
    `The code is covered by 76 automated tests (pytest), run against an in-process fake of AWS (moto ${c(53)}) and a scripted fake database. Key guarantees were mutation-tested: deliberately removing the teardown call, removing a Catch rule from the workflow, disabling IAM database authentication or the concurrent-run protection each makes the tests fail. The templates pass cfn-lint and the official SAM translator. Testing on AWS also found two real defects, both fixed: the straggler sweep could delete an instance belonging to a concurrent run, and redeploying without the alert-email parameter would silently remove the email subscription.`,
  ),
);

add(
  H1("Conclusion"),
  P(
    "RestoreCheck turns the principle \"a backup isn't real until you've tested the restore\" into an automated, inexpensive and secure service. It restores the newest database backup on a schedule, proves that the restored data is complete and intact, measures the recovery time, alerts when anything is wrong and always cleans up after itself. On AWS it classified all six scenarios correctly, including a single-value corruption that simpler checks miss, with a median restore time of about seven minutes.",
  ),
  P(
    "**Limitations.** The prototype verifies one engine (PostgreSQL on RDS) against a synthetic dataset; expectations are a static configuration file; restore time is measured to the nearest minute; and the demo source database accepts connections from a single administrator IP address so that it can be seeded.",
  ),
  P(
    "**Future work.** Verifying EC2/EBS volume snapshots and other engines; multi-region restore testing; deriving expectations automatically from the source database; using the checker as the validation step of AWS Backup restore testing; moving the schedule to EventBridge Scheduler; and a live dashboard served from S3 and CloudFront.",
  ),
);

// References in order of first citation, then any not cited in the text.
const referenceOrder = [...cited, ...Object.keys(REFS).map(Number).filter((n) => !cited.includes(n))];
add(
  H1("References"),
  ...referenceOrder.map(
    (n, i) =>
      new Paragraph({
        children: [new TextRun({ text: `[${i + 1}] ` }), ...runs(REFS[n])],
        indent: { left: 567, hanging: 567 },
        spacing: { after: 100 },
      }),
  ),
);

add(
  H1("Appendix: Research paper"),
  P("[Optional: add the link to the research paper (Word format) if one is prepared.]"),
);

// ---------------------------------------------------------------- document
const doc = new Document({
  creator: TEAM.map(([, name]) => name).join(", "),
  title: TITLE,
  styles: {
    default: { document: { run: { font: "Times New Roman", size: 24, color: BLACK } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Times New Roman", size: 28, bold: true, color: BLACK },
        paragraph: { spacing: { before: 360, after: 160 }, keepNext: true, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Times New Roman", size: 24, bold: true, color: BLACK },
        paragraph: { spacing: { before: 240, after: 120 }, keepNext: true, outlineLevel: 1 },
      },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 283 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 340 } } } }] },
    ],
  },
  sections: [
    {
      properties: { page: { margin: { top: 1300, bottom: 1300, left: 1440, right: 1440 } } },
      headers: {
        default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BLACK, space: 4 } }, children: [new TextRun({ text: "RestoreCheck  |  BCSE355L Cloud Architecture Design  |  DA-III", size: 18, italics: true })] })] }),
      },
      footers: {
        default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 20 })] })] }),
      },
      children: body,
    },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(OUT, buffer);
  console.log(`Wrote ${OUT} (${cited.length} references cited in the text, ${referenceOrder.length} listed)`);
});
