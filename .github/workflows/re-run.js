module.exports = async ({ github, context }) => {
  const {
    repo: { owner, repo },
  } = context;

  const { data: pr } = await github.rest.pulls.get({
    owner,
    repo,
    pull_number: context.issue.number,
  });

  const checkRuns = await github.paginate(github.rest.checks.listForRef, {
    owner,
    repo,
    ref: pr.head.sha,
  });
  const runIdsToRerun = checkRuns
    // Select failed github actions runs
    .filter(
      ({ name, status, conclusion, app: { slug } }) =>
        slug === "github-actions" &&
        status === "completed" &&
        (conclusion === "failure" || conclusion === "cancelled") &&
        name !== "re-run"
    )
    .map(
      ({
        // Example: https://github.com/mlflow/mlflow/actions/runs/10675586265/job/29587793829
        //                                                        ^^^^^^^^^^^ run_id
        html_url,
      }) => html_url.match(/\/actions\/runs\/(\d+)/)[1]
    );

  for (const run_id of [...new Set(runIdsToRerun)]) {
    console.log(`Re-running ${run_id}`);
    await github.rest.actions.reRunWorkflowFailedJobs({
      repo,
      owner,
      run_id,
    });
  }
};
