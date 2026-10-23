// (C) 2026 GoodData Corporation
const CLEAN = '<!-- gdcloud-clean -->';

function boundedBody(body, run) {
  if (body.length <= 58000) return body;
  let excerpt = body.slice(0, 56000);
  excerpt = excerpt.slice(0, excerpt.lastIndexOf('\n'));
  let fence = null;
  for (const line of excerpt.split('\n')) {
    const match = line.match(/^(`{3,}|~{3,})/);
    if (!match) continue;
    if (!fence) fence = match[1];
    else if (match[1][0] === fence[0] && match[1].length >= fence.length) fence = null;
  }
  return excerpt + (fence ? `\n${fence}` : '') +
    `\n\nReport truncated. [Complete report in the check summary](${run}).`;
}

module.exports = async function publish({ github, context, core, marker, body = '' }) {
  const pr = context.payload.pull_request;
  if (!pr) return;
  if (!marker || !/^<!--[\w .:-]+-->$/.test(marker)) throw new Error('A unique HTML comment marker is required.');
  if (pr.head.repo?.full_name !== context.payload.repository.full_name || context.actor === 'dependabot[bot]') {
    core.info('PR comments unavailable for this token; see the check summary.');
    return;
  }
  const repo = { owner: context.repo.owner, repo: context.repo.repo };
  const run = `${process.env.GITHUB_SERVER_URL || 'https://github.com'}/${repo.owner}/${repo.repo}/actions/runs/${context.runId}`;
  const ours = item => item.user?.type === 'Bot' && item.body?.startsWith(marker);
  try {
    const { data: current } = await github.rest.pulls.get({ ...repo, pull_number: pr.number });
    if (current.state !== 'open' || current.head.sha !== pr.head.sha) {
      core.info('PR closed or head changed; leaving current findings alone.');
      return;
    }
    // Findings used to live in a file-level review thread. Delete it so the
    // report has one home; remove once consumers' older PRs have aged out.
    const threads = await github.paginate(github.rest.pulls.listReviewComments, { ...repo, pull_number: pr.number, per_page: 100 });
    for (const comment of threads.filter(ours)) {
      await github.rest.pulls.deleteReviewComment({ ...repo, comment_id: comment.id });
    }
    const comments = await github.paginate(github.rest.issues.listComments, { ...repo, issue_number: pr.number, per_page: 100 });
    const existing = comments.find(ours);
    if (!body.trim()) {
      if (!existing || existing.body.includes(CLEAN)) return;
      const previous = existing.body.slice(marker.length).trim();
      body = `${marker}\n${CLEAN}\n✅ No findings as of \`${pr.head.sha.slice(0, 7)}\`. [Check run](${run}).` +
        (previous ? `\n\n<details><summary>Previous findings</summary>\n\n${previous}\n\n</details>` : '');
    } else {
      body = `${marker}\n${boundedBody(body, run)}`;
    }
    if (!existing) await github.rest.issues.createComment({ ...repo, issue_number: pr.number, body });
    else if (existing.body !== body) await github.rest.issues.updateComment({ ...repo, comment_id: existing.id, body });
  } catch (error) {
    if (error.status !== 403 && !error.errors?.some(item => item.type === 'FORBIDDEN')) throw error;
    core.warning('Token cannot publish PR comments; see the check summary and logs.');
  }
};
