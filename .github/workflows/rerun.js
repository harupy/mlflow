module.exports = async ({ github, context }) => {
  const {
    repo: { owner, repo },
  } = context;

  await github.rest.reactions.createForIssueComment({
    owner,
    repo,
    comment_id: context.payload.comment.id,
    content: "rocket",
  });

  if (!["OWNER", "MEMBER", "COLLABORATOR"].includes(context.payload.comment.author_association)) {
    await github.rest.issues.createComment({
      owner,
      repo,
      issue_number: context.issue.number,
      body: "Only maintainers and collaborators can use the `/rerun` command.",
    });
    return;
  }

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
    // Select failed/cancelled github action runs
    .filter(
      ({ name, status, conclusion, app: { slug } }) =>
        slug === "github-actions" &&
        status === "completed" &&
        (conclusion === "failure" || conclusion === "cancelled") &&
        name !== "rerun"
    )
    .map(
      ({
        // Example: https://github.com/mlflow/mlflow/actions/runs/10675586265/job/29587793829
        //                                                        ^^^^^^^^^^^ run_id
        html_url,
      }) => html_url.match(/\/actions\/runs\/(\d+)/)[1]
    );

  const uniqueRunIds = [...new Set(runIdsToRerun)];
  const promises = uniqueRunIds.map(async (run_id) => {
    console.log(`Rerunning https://github.com/${owner}/${repo}/actions/runs/${run_id}`);
    await github.rest.actions.reRunWorkflowFailedJobs({
      repo,
      owner,
      run_id,
    });
  });
  await Promise.all(promises);
};
