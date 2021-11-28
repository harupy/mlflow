const getData = async (context, github) => {
  const { workflow, runId } = context;
  const { owner, repo } = context.repo;
  const pull_number = context.issue.number;
  const pr = await github.pulls.get({ owner, repo, pull_number });
  const head_sha = pr.data.head.sha;
  const run_url = `https://github.com/${owner}/${repo}/actions/runs/${runId}`;
  const pr_url = `https://github.com/${owner}/${repo}/pull/${pull_number}`;
  return {
    owner,
    repo,
    head_sha,
    workflow,
    run_url,
    pr_url,
  };
};

const objectToMarkdownTable = (obj) => {
  return [
    '|Key|Value|',
    '|---|-----|',
    ...Object.entries(obj).map(([key, value]) => `|${key}|${value}|`),
  ].join('\n');
};

const createCheckRun = async (context, github) => {
  const { owner, repo, head_sha, workflow, run_url, pr_url } = await getData(context, github);
  const status = 'in_progress';
  const summaryObject = {
    head_sha,
    run_url,
    pr_url,
    status: status,
    conclusion: '-',
  };
  const summary = objectToMarkdownTable(summaryObject);
  const check_run = await github.checks.create({
    owner,
    repo,
    head_sha,
    status,
    name: workflow,
    output: {
      title: workflow,
      summary,
    },
  });
  return check_run.data.id;
};

const updateCheckRun = async (context, github, check_run_id, needs) => {
  const { owner, repo, head_sha, workflow, run_url, pr_url } = await getData(context, github);
  const failed = Object.values(needs).some(({ result }) => result === 'failure');
  const conclusion = failed ? 'failure' : 'success';
  const summaryObject = {
    head_sha,
    run_url,
    pr_url,
    status: 'completed',
    conclusion: conclusion,
  };
  const summary = objectToMarkdownTable(summaryObject);
  await github.checks.update({
    owner,
    repo,
    check_run_id,
    conclusion,
    output: {
      title: workflow,
      summary,
    },
  });
};

module.exports = {
  createCheckRun,
  updateCheckRun,
};
