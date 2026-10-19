// AFK loop: one GitHub issue at a time, implemented and reviewed in a Docker
// sandbox, landed as a pull request.
//
// Per issue:
//   1. Pick   (host)    — the oldest open `ready-for-agent` issue that is not a
//                         spec, not blocked, and has no open pull request yet.
//   2. Build  (sandbox) — an implementer agent works it test-first and commits
//                         on `sandcastle/issue-<n>`.
//   3. Review (sandbox) — a reviewer agent runs /code-review on that branch and
//                         fixes what it finds.
//   4. Check  (sandbox) — lint, API tests, typecheck and web tests.
//   5. Land   (host)    — push the branch and open a PR that closes the issue;
//                         a draft when a check failed. A blocked implementer
//                         instead comments on the issue and hands it back to
//                         triage.
//
// The sandbox holds no GitHub credentials: every GitHub read and write happens
// here, on the host, through your own `gh` login and git hooks.
//
// Usage (from a clean checkout of the branch PRs should target, usually main):
//   pnpm sandcastle            — up to MAX_ISSUES issues
//   pnpm sandcastle 17         — just issue #17

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { parseEnv } from "node:util";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const MAX_ISSUES = 5;
const READY_LABEL = "ready-for-agent";
const HANDBACK_LABEL = "needs-triage";
const IMPLEMENTER = sandcastle.claudeCode("claude-opus-5-5", { effort: "high" });
const REVIEWER = sandcastle.claudeCode("claude-opus-5-5", { effort: "high" });

// The sandbox reaches Compose's Postgres by service name, on its own database
// so a run never touches your development data (tests add a `_test` suffix).
const SANDBOX_DATABASE = "leprechaun_sandcastle";

// Package caches shared by every sandbox, so each fresh container does not
// download the world. Host paths, created on first run.
const CACHE_ROOT = join(homedir(), ".cache", "sandcastle", "open-leprechaun");

const CHECKS = [
  { name: "lint", command: "pnpm lint" },
  { name: "api tests", command: "apps/api/.venv/bin/python -m pytest -c apps/api/pyproject.toml -q" },
  { name: "typecheck", command: "pnpm typecheck" },
  { name: "web tests", command: "pnpm test:web" },
];

// ---------------------------------------------------------------------------
// Host helpers
// ---------------------------------------------------------------------------

const sh = (cmd: string, args: string[]) =>
  execFileSync(cmd, args, { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] }).trim();

const gh = (...args: string[]) => sh("gh", args);

type Issue = {
  number: number;
  title: string;
  body: string;
  labels: { name: string }[];
  comments: { author: { login: string }; body: string }[];
};

const repo = gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner");

function viewIssue(number: number): Issue {
  return JSON.parse(gh("issue", "view", String(number), "--json", "number,title,body,labels,comments"));
}

function parentOf(number: number): Issue | undefined {
  try {
    return viewIssue(Number(gh("api", `repos/${repo}/issues/${number}/parent`, "--jq", ".number")));
  } catch {
    return undefined; // 404: not a sub-issue
  }
}

function isBlocked(number: number): boolean {
  const open = gh("api", `repos/${repo}/issues/${number}`, "--jq", ".issue_dependencies_summary.blocked_by // 0");
  return Number(open) > 0;
}

const branchFor = (number: number) => `sandcastle/issue-${number}`;

function hasOpenPullRequest(number: number): boolean {
  return gh("pr", "list", "--head", branchFor(number), "--state", "open", "--json", "number", "--jq", "length") !== "0";
}

function nextIssue(skip: Set<number>): number | undefined {
  const candidates: { number: number; labels: { name: string }[] }[] = JSON.parse(
    gh("issue", "list", "--label", READY_LABEL, "--state", "open", "--limit", "100", "--json", "number,labels"),
  );
  return candidates
    .filter((i) => !i.labels.some((l) => l.name === "spec"))
    .map((i) => i.number)
    .sort((a, b) => a - b)
    .find((n) => !skip.has(n) && !isBlocked(n) && !hasOpenPullRequest(n));
}

function renderIssue(issue: Issue, heading: string): string {
  const comments = issue.comments
    .map((c) => `**@${c.author.login}:**\n\n${c.body}`)
    .join("\n\n---\n\n");
  return [
    `## ${heading}: #${issue.number} — ${issue.title}`,
    `Labels: ${issue.labels.map((l) => l.name).join(", ") || "none"}`,
    issue.body || "_(no body)_",
    comments && `### Comments\n\n${comments}`,
  ]
    .filter(Boolean)
    .join("\n\n");
}

/** The last `<tag>…</tag>` in an agent's output — the prompt itself may quote the tag. */
function lastTag(stdout: string, tag: string): string | undefined {
  const matches = [...stdout.matchAll(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`, "g"))];
  return matches.at(-1)?.[1]?.trim();
}

/** Agent text for the PR body, minus the lines the body adds itself. */
function prSection(text: string | undefined): string | undefined {
  return text
    ?.split("\n")
    .filter((line) => !/^🤖 Generated with|^(Refs|Closes) #\d+\s*$/.test(line.trim()))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * Runs text the agent wrote through the repo's commit-msg guard before it is
 * published, since no git hook sees PR or issue text. No hook (a fresh clone),
 * no check — AGENTS.md says to recreate it.
 */
function passesFinancialDataGuard(text: string): boolean {
  const hook = ".git/hooks/commit-msg";
  if (!existsSync(hook)) {
    console.warn(`  ! ${hook} missing — agent text goes out unchecked.`);
    return true;
  }
  const file = join(mkdtempSync(join(tmpdir(), "sandcastle-")), "text");
  writeFileSync(file, text);
  try {
    execFileSync(hook, [file], { stdio: "inherit" });
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Preflight
// ---------------------------------------------------------------------------

if (sh("git", ["status", "--porcelain"]) !== "") {
  throw new Error("Working tree is dirty. Commit or stash first — branches are cut from HEAD.");
}
const baseBranch = sh("git", ["rev-parse", "--abbrev-ref", "HEAD"]);
console.log(`Base branch: ${baseBranch}`);

sh("pnpm", ["db:up"]);
const postgresContainer = sh("docker", ["compose", "ps", "--quiet", "postgres"]);
const network = sh("docker", [
  "inspect", postgresContainer, "--format", "{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}",
]);
const hostEnv = parseEnv(readFileSync(".env", "utf8"));
const databaseUrl =
  `postgresql+psycopg://${hostEnv.POSTGRES_USER}:${hostEnv.POSTGRES_PASSWORD}@postgres:5432/${SANDBOX_DATABASE}`;

const pipCache = join(CACHE_ROOT, "pip");
const pnpmStore = join(CACHE_ROOT, "pnpm-store");
mkdirSync(pipCache, { recursive: true });
mkdirSync(pnpmStore, { recursive: true });

const sandboxProvider = () =>
  docker({
    network,
    env: {
      DATABASE_URL: databaseUrl,
      // Without this pnpm keeps a store inside the worktree (the mounted cache
      // is another filesystem), which dirties it and invites a commit.
      pnpm_config_store_dir: "/home/agent/.local/share/pnpm/store",
    },
    mounts: [
      { hostPath: pipCache, sandboxPath: "/home/agent/.cache/pip" },
      { hostPath: pnpmStore, sandboxPath: "/home/agent/.local/share/pnpm/store" },
    ],
  });

const hooks = {
  sandbox: {
    onSandboxReady: [
      // The API refuses to start without .env; DATABASE_URL above overrides its host address.
      { command: "test -f .env || cp .env.example .env" },
      { command: "pnpm install --frozen-lockfile && pnpm setup:api", timeoutMs: 900_000 },
    ],
  },
};

// ---------------------------------------------------------------------------
// One issue
// ---------------------------------------------------------------------------

type Outcome = "pr" | "draft-pr" | "blocked" | "no-commits" | "failed";

async function work(number: number): Promise<Outcome> {
  const issue = viewIssue(number);
  const parent = parentOf(number);
  const context = [renderIssue(issue, "Issue"), parent && renderIssue(parent, "Parent spec")]
    .filter(Boolean)
    .join("\n\n");
  const branch = branchFor(number);
  const promptArgs = { ISSUE_NUMBER: String(number), ISSUE: context };

  console.log(`\n=== #${number} ${issue.title} → ${branch} ===\n`);

  const sandbox = await sandcastle.createSandbox({ branch, sandbox: sandboxProvider(), hooks });
  let implement: sandcastle.SandboxRunResult;
  let review: sandcastle.SandboxRunResult | undefined;
  const failedChecks: string[] = [];
  try {
    implement = await sandbox.run({
      name: `implement #${number}`,
      agent: IMPLEMENTER,
      promptFile: "./.sandcastle/implement-prompt.md",
      promptArgs,
      completionSignal: ["<promise>COMPLETE</promise>", "<promise>BLOCKED</promise>"],
      idleTimeoutSeconds: 1200,
    });

    if (implement.completionSignal === "<promise>BLOCKED</promise>") {
      const reason = lastTag(implement.stdout, "summary") ?? "The agent stopped without saying why.";
      const comment = `🤖 The AFK agent could not finish this issue and handed it back for triage.\n\n${reason}`;
      if (passesFinancialDataGuard(comment)) {
        gh("issue", "comment", String(number), "--body", comment);
      }
      gh("issue", "edit", String(number), "--remove-label", READY_LABEL, "--add-label", HANDBACK_LABEL);
      return "blocked";
    }
    if (implement.commits.length === 0) {
      console.log(`  No commits for #${number}; leaving it as is.`);
      return "no-commits";
    }

    review = await sandbox.run({
      name: `review #${number}`,
      agent: REVIEWER,
      promptFile: "./.sandcastle/review-prompt.md",
      promptArgs,
      idleTimeoutSeconds: 1200,
    });

    for (const check of CHECKS) {
      const result = await sandbox.exec(check.command);
      console.log(`  ${result.exitCode === 0 ? "✓" : "✗"} ${check.name}`);
      if (result.exitCode !== 0) failedChecks.push(check.name);
    }
  } finally {
    const closed = await sandbox.close();
    if (closed.preservedWorktreePath) {
      console.warn(`  ! Uncommitted changes left in ${closed.preservedWorktreePath}`);
    }
  }

  const title =
    lastTag(implement.stdout, "pr-title") ??
    sh("git", ["log", "--reverse", "--format=%s", `${baseBranch}..${branch}`]).split("\n")[0]!;
  const body = [
    `Closes #${number}`,
    prSection(lastTag(implement.stdout, "summary")) ?? "",
    `## Review\n\n${(review && prSection(lastTag(review.stdout, "review"))) || "_The reviewer left no summary._"}`,
    `## Checks\n\n${CHECKS.map((c) => `- [${failedChecks.includes(c.name) ? " " : "x"}] ${c.name}`).join("\n")}`,
    "🤖 Generated with [Claude Code](https://claude.com/claude-code) via [Sandcastle](https://github.com/mattpocock/sandcastle)",
  ].join("\n\n");

  if (!passesFinancialDataGuard(`${title}\n\n${body}`)) {
    console.error(`  ✗ PR text for #${number} tripped the financial-data guard; branch ${branch} kept local.`);
    return "failed";
  }

  // The pre-push hook runs here, on the host, like any push of yours.
  sh("git", ["push", "--set-upstream", "origin", branch]);
  const draft = failedChecks.length > 0;
  const url = gh(
    "pr", "create", "--base", baseBranch, "--head", branch, "--title", title, "--body", body,
    ...(draft ? ["--draft"] : []),
  );
  console.log(`  → ${draft ? "draft " : ""}PR ${url}`);
  return draft ? "draft-pr" : "pr";
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

const only = process.argv[2] ? Number(process.argv[2]) : undefined;
const attempted = new Set<number>();
const outcomes: string[] = [];

for (let i = 0; i < (only ? 1 : MAX_ISSUES); i++) {
  const number = only ?? nextIssue(attempted);
  if (number === undefined) {
    console.log("\nNo unblocked ready-for-agent issues left.");
    break;
  }
  attempted.add(number);
  try {
    outcomes.push(`#${number}: ${await work(number)}`);
  } catch (error) {
    console.error(`  ✗ #${number} failed:`, error);
    outcomes.push(`#${number}: failed`);
  }
}

console.log(`\nDone.\n${outcomes.map((o) => `  ${o}`).join("\n") || "  nothing to do"}`);
