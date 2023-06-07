module.exports = async ({ context, github }) => {
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const prNumber = context.payload.pull_request.number;
  const headSha = context.payload.pull_request.head.sha;

  // Get all workflow runs associated with the PR.
  const prRuns = await github.rest.actions.listWorkflowRunsForRepo({
    owner,
    repo,
    head_sha: headSha,
    event: "pull_request",
    status: "in_progress",
    per_page: 100,
  });
  console.log(prRuns.data.workflow_runs);

  // Cancel the runs
  for (const run of prRuns.data.workflow_runs) {
    await github.rest.actions.cancelWorkflowRun({
      owner,
      repo,
      run_id: run.id,
    });
  }
};
