module.exports = async ({ context, github }) => {
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const prNumber = context.payload.pull_request.number;
  const headSha = context.payload.pull_request.head.sha;

  // Get all workflow runs associated with the PR.
  const runs = await github.rest.actions.listWorkflowRunsForRepo({
    owner,
    repo,
    head_sha: headSha,
    event: "pull_request",
    status: "in_progress",
    per_page: 100,
  });
  console.log(runs.data.workflow_runs);

  // Filter to only get runs associated with this PR.
  const prRuns = runs.data.workflow_runs.filter(({ pull_requests }) =>
    pull_requests.some(({ number }) => number === prNumber)
  );

  console.log(prRuns);

  // Cancel the runs
  for (const run of prRuns) {
    await github.rest.actions.cancelWorkflowRun({
      owner,
      repo,
      run_id: run.id,
    });
  }
};
