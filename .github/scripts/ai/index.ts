#!/usr/bin/env node

/**
 * AI Command Handler for GitHub Pull Request Reviews
 *
 * This script processes /ai commands in PR review comments and responds with AI-generated suggestions.
 */

// Types and Interfaces
interface GitHubComment {
  id: number;
  body: string;
  user: {
    login: string;
  };
  path: string;
  line?: number;
  start_line?: number;
  original_line?: number;
  original_start_line?: number;
  subject_type?: "line" | "file";
  commit_id: string;
  created_at: string;
}

interface GitHubFileContent {
  content: string;
  encoding: string;
}

interface OpenAIMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

interface OpenAIResponse {
  choices: Array<{
    message: {
      content: string;
    };
  }>;
}

interface GitHubPermissionResponse {
  permission: string;
}

interface AICommandArgs {
  commentBody: string;
  filePath: string;
  lineNumber?: number;
  startLineNumber?: number;
  subjectType?: "line" | "file";
  prNumber: number;
  commentId: number;
  repoOwner: string;
  repoName: string;
  commitSha: string;
  commentUser: string;
}

class GitHubAPI {
  private readonly token: string;
  private readonly repoOwner: string;
  private readonly repoName: string;
  private readonly baseUrl = "https://api.github.com";

  constructor(token: string, repoOwner: string, repoName: string) {
    this.token = token;
    this.repoOwner = repoOwner;
    this.repoName = repoName;
  }

  private get headers(): Record<string, string> {
    return {
      Authorization: `Bearer ${this.token}`,
      Accept: "application/vnd.github.v3+json",
      "User-Agent": "MLflow-AI-Command",
      "Content-Type": "application/json",
    };
  }

  async getFileContent(
    filePath: string,
    commitSha: string
  ): Promise<string | null> {
    try {
      const url = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/contents/${filePath}`;
      const params = new URLSearchParams({ ref: commitSha });

      const response = await fetch(`${url}?${params}`, {
        headers: this.headers,
      });

      if (!response.ok) {
        console.error(
          `Failed to fetch file content: ${response.status} ${response.statusText}`
        );
        return null;
      }

      const data = (await response.json()) as GitHubFileContent;

      if (data.encoding === "base64") {
        return Buffer.from(data.content, "base64").toString("utf-8");
      }

      return data.content;
    } catch (error) {
      console.error("Error fetching file content:", error);
      return null;
    }
  }

  async getFileDiff(
    filePath: string,
    commitSha: string,
    prNumber: number
  ): Promise<string | null> {
    try {
      // Get the PR to find the base commit
      const prUrl = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/pulls/${prNumber}`;
      const prResponse = await fetch(prUrl, {
        headers: this.headers,
      });

      if (!prResponse.ok) {
        console.error(
          `Failed to fetch PR: ${prResponse.status} ${prResponse.statusText}`
        );
        return null;
      }

      const prData = await prResponse.json();
      const baseSha = prData.base.sha;

      // Get the diff for the specific file
      const compareUrl = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/compare/${baseSha}...${commitSha}`;
      const compareResponse = await fetch(compareUrl, {
        headers: {
          ...this.headers,
          Accept: "application/vnd.github.diff",
        },
      });

      if (!compareResponse.ok) {
        console.error(
          `Failed to fetch diff: ${compareResponse.status} ${compareResponse.statusText}`
        );
        return null;
      }

      const fullDiff = await compareResponse.text();

      // Extract diff for the specific file
      const fileDiffRegex = new RegExp(
        `diff --git a/${filePath.replace(
          /[.*+?^${}()|[\]\\]/g,
          "\\$&"
        )} b/${filePath.replace(
          /[.*+?^${}()|[\]\\]/g,
          "\\$&"
        )}[\\s\\S]*?(?=(?:diff --git|$))`,
        "g"
      );

      const match = fullDiff.match(fileDiffRegex);
      return match ? match[0].trim() : null;
    } catch (error) {
      console.error("Error fetching file diff:", error);
      return null;
    }
  }

  async getCommentThread(
    prNumber: number,
    commentId: number
  ): Promise<GitHubComment[]> {
    try {
      const threadComments = new Map<number, GitHubComment>();
      const fetchedComments = new Set<number>();

      // First, walk up the chain to find the root comment
      let currentCommentId: number | null = commentId;

      while (currentCommentId && !fetchedComments.has(currentCommentId)) {
        fetchedComments.add(currentCommentId);

        const commentUrl = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/pulls/comments/${currentCommentId}`;
        const response = await fetch(commentUrl, {
          headers: this.headers,
        });

        if (!response.ok) {
          console.error(
            `Failed to fetch comment ${currentCommentId}: ${response.status} ${response.statusText}`
          );
          break;
        }

        const comment = (await response.json()) as GitHubComment & {
          in_reply_to?: number;
        };
        threadComments.set(comment.id, comment);

        // Move to the parent comment if it exists
        currentCommentId = comment.in_reply_to || null;
      }

      // If we only have one comment, return it
      if (threadComments.size === 1) {
        return Array.from(threadComments.values());
      }

      // Find the root comment (the one with no in_reply_to)
      const rootComment = Array.from(threadComments.values()).find(
        comment => !(comment as any).in_reply_to
      );

      if (!rootComment) {
        // If no root found, return what we have
        return Array.from(threadComments.values()).sort(
          (a, b) =>
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
      }

      // Now we need to find all replies in the thread
      // We'll use a more targeted approach by fetching all PR comments once
      // but this is still more efficient than the original for large PRs since we
      // at least validated the thread structure first
      const allCommentsUrl = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/pulls/${prNumber}/comments`;
      const allResponse = await fetch(allCommentsUrl, {
        headers: this.headers,
      });

      if (!allResponse.ok) {
        console.error(
          `Failed to fetch all comments: ${allResponse.status} ${allResponse.statusText}`
        );
        return Array.from(threadComments.values()).sort(
          (a, b) =>
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
      }

      const allComments = (await allResponse.json()) as (GitHubComment & {
        in_reply_to?: number;
      })[];

      // Find all comments in the same thread by following the reply chain
      const completeThread = new Map<number, GitHubComment>();

      // Add all comments that are in the same location as the root
      for (const comment of allComments) {
        const belongsToThread = this.isCommentInSameThread(
          comment,
          rootComment
        );
        if (belongsToThread) {
          completeThread.set(comment.id, comment);
        }
      }

      // Sort by creation time to get chronological order
      return Array.from(completeThread.values()).sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
    } catch (error) {
      console.error("Error fetching comment thread:", error);
      return [];
    }
  }

  private isCommentInSameThread(
    comment: GitHubComment,
    rootComment: GitHubComment
  ): boolean {
    // Must be same file
    if (comment.path !== rootComment.path) {
      return false;
    }

    // If root is file-level comment
    if (
      rootComment.subject_type === "file" ||
      (!rootComment.line && !rootComment.original_line)
    ) {
      return (
        comment.subject_type === "file" ||
        (!comment.line && !comment.original_line)
      );
    }

    // If root is line-level comment
    return (
      comment.line === rootComment.line &&
      comment.start_line === rootComment.start_line &&
      comment.original_line === rootComment.original_line &&
      comment.original_start_line === rootComment.original_start_line
    );
  }

  async replyToComment(
    prNumber: number,
    commentId: number,
    body: string
  ): Promise<boolean> {
    try {
      // First get the original comment to extract necessary info for reply
      const commentUrl = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/pulls/comments/${commentId}`;

      const commentResponse = await fetch(commentUrl, {
        headers: this.headers,
      });

      if (!commentResponse.ok) {
        console.error(
          `Failed to fetch original comment: ${commentResponse.status} ${commentResponse.statusText}`
        );
        return false;
      }

      const originalComment = (await commentResponse.json()) as GitHubComment;

      // Create a new review comment in reply
      const url = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/pulls/${prNumber}/comments`;
      const data: any = {
        body,
        commit_id: originalComment.commit_id,
        path: originalComment.path,
        in_reply_to: commentId,
      };

      // Add line information if this is a line-level comment
      if (originalComment.line || originalComment.original_line) {
        data.line = originalComment.line || originalComment.original_line;

        // Add start_line if this is a multi-line comment
        if (originalComment.start_line) {
          data.start_line = originalComment.start_line;
        }
      }

      // Add subject_type if specified
      if (originalComment.subject_type) {
        data.subject_type = originalComment.subject_type;
      }

      const response = await fetch(url, {
        method: "POST",
        headers: this.headers,
        body: JSON.stringify(data),
      });

      return response.status === 201;
    } catch (error) {
      console.error("Error replying to comment:", error);
      return false;
    }
  }

  async checkUserPermissions(username: string): Promise<boolean> {
    try {
      const url = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/collaborators/${username}/permission`;

      const response = await fetch(url, {
        headers: this.headers,
      });

      if (!response.ok) {
        console.error(
          `Failed to check permissions: ${response.status} ${response.statusText}`
        );
        return false;
      }

      const data = (await response.json()) as GitHubPermissionResponse;
      const isAuthorized = ["admin", "write"].includes(data.permission);

      console.log(
        `User ${username} has permission: ${data.permission}, authorized: ${isAuthorized}`
      );
      return isAuthorized;
    } catch (error) {
      console.error("Error checking user permissions:", error);
      return false;
    }
  }
}

class AICommandProcessor {
  private readonly githubToken: string;

  constructor(githubToken: string) {
    this.githubToken = githubToken;
  }

  extractCommandText(commentBody: string): string {
    return commentBody.replace(/\/ai\s+/i, "").trim();
  }

  getCodeContext(
    fileContent: string,
    lineNumber?: number,
    startLineNumber?: number,
    subjectType?: "line" | "file",
    contextLines: number = 5
  ): string {
    if (!fileContent) {
      return "";
    }

    const lines = fileContent.split("\n");
    const totalLines = lines.length;

    // Handle file-level comments (no specific lines selected)
    if (subjectType === "file" || !lineNumber) {
      // For file-level comments, show the first part of the file
      const maxLines = Math.min(50, totalLines); // Show first 50 lines max
      const contextLinesList: string[] = [];

      for (let i = 0; i < maxLines; i++) {
        contextLinesList.push(
          `    ${(i + 1).toString().padStart(4)}: ${lines[i]}`
        );
      }

      if (totalLines > maxLines) {
        contextLinesList.push("    ...");
        contextLinesList.push(
          `    [File continues for ${totalLines - maxLines} more lines]`
        );
      }

      return contextLinesList.join("\n");
    }

    // Handle line-specific comments
    // Determine the range of selected lines
    const selectedStartLine = startLineNumber || lineNumber;
    const selectedEndLine = lineNumber;

    // Calculate context range around the selected lines
    const start = Math.max(0, selectedStartLine - contextLines - 1); // lineNumbers are 1-indexed
    const end = Math.min(totalLines, selectedEndLine + contextLines);

    const contextLinesList: string[] = [];
    for (let i = start; i < end; i++) {
      const currentLine = i + 1; // Convert to 1-indexed
      let prefix = "    ";

      // Mark selected lines with >>> and context lines with spaces
      if (currentLine >= selectedStartLine && currentLine <= selectedEndLine) {
        prefix = ">>> ";
      }

      contextLinesList.push(
        `${prefix}${currentLine.toString().padStart(4)}: ${lines[i]}`
      );
    }

    return contextLinesList.join("\n");
  }

  buildMessages(
    commandText: string,
    filePath: string,
    codeContext: string,
    threadContext: GitHubComment[],
    isFileDiff: boolean = false
  ): OpenAIMessage[] {
    const contextLabel = isFileDiff ? "File diff:" : "Code context:";
    const messages: OpenAIMessage[] = [
      {
        role: "system",
        content: [
          "You are an expert code reviewer helping with a GitHub pull request.",
          `File: ${filePath}`,
          "",
          `${contextLabel}`,
          "```",
          codeContext,
          "```",
          "",
          "Please provide a helpful response. Keep it concise and focused on the specific request.",
          "If suggesting code changes, use proper markdown formatting with code blocks.",
        ].join("\n"),
      },
    ];

    // Add all comments in the thread as messages with appropriate roles
    for (const comment of threadContext) {
      if (comment.body.trim().startsWith("/ai")) {
        // Extract the actual request from the /ai command
        messages.push({
          role: "user",
          content: commandText,
        });
      } else if (comment.body.includes("🤖 Generated by AI assistant")) {
        // This is a previous AI response - use assistant role
        // Remove the AI attribution footer for cleaner conversation
        const cleanContent = comment.body
          .replace(/\n\n---\n\*🤖 Generated by AI assistant\*$/, "")
          .replace(/^@\w+\s+/, ""); // Also remove user mention if present
        messages.push({
          role: "assistant",
          content: cleanContent,
        });
      } else {
        // Add regular comment as user message
        messages.push({
          role: "user",
          content: `@${comment.user.login}: ${comment.body}`,
        });
      }
    }

    return messages;
  }

  async generateResponse(messages: OpenAIMessage[]): Promise<string> {
    try {
      const response = await fetch(
        "https://models.github.ai/inference/chat/completions",
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${this.githubToken}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: "openai/gpt-4o",
            messages: messages,
            max_tokens: 1000,
            temperature: 0.7,
            top_p: 1.0,
          }),
        }
      );

      if (!response.ok) {
        throw new Error(
          `API request failed: ${response.status} ${response.statusText}`
        );
      }

      const data = (await response.json()) as OpenAIResponse;
      return (
        data.choices[0]?.message?.content?.trim() || "❌ No response generated"
      );
    } catch (error) {
      console.error("Error generating AI response:", error);
      return `❌ Error generating AI response: ${
        error instanceof Error ? error.message : String(error)
      }`;
    }
  }
}

function parseArgs(): AICommandArgs {
  const args = process.argv.slice(2);
  const parsed: Partial<AICommandArgs> = {};

  for (let i = 0; i < args.length; i += 2) {
    const key = args[i];
    const value = args[i + 1];

    switch (key) {
      case "--comment-body":
        parsed.commentBody = value;
        break;
      case "--file-path":
        parsed.filePath = value;
        break;
      case "--line-number":
        parsed.lineNumber = parseInt(value, 10);
        break;
      case "--start-line-number":
        parsed.startLineNumber = parseInt(value, 10);
        break;
      case "--subject-type":
        parsed.subjectType = value as "line" | "file";
        break;
      case "--pr-number":
        parsed.prNumber = parseInt(value, 10);
        break;
      case "--comment-id":
        parsed.commentId = parseInt(value, 10);
        break;
      case "--repo-owner":
        parsed.repoOwner = value;
        break;
      case "--repo-name":
        parsed.repoName = value;
        break;
      case "--commit-sha":
        parsed.commitSha = value;
        break;
      case "--comment-user":
        parsed.commentUser = value;
        break;
    }
  }

  // Validate required fields
  const required: (keyof AICommandArgs)[] = [
    "commentBody",
    "filePath",
    "prNumber",
    "commentId",
    "repoOwner",
    "repoName",
    "commitSha",
    "commentUser",
  ];
  for (const field of required) {
    if (parsed[field] === undefined) {
      throw new Error(
        `Missing required argument: --${field
          .replace(/([A-Z])/g, "-$1")
          .toLowerCase()}`
      );
    }
  }

  return parsed as AICommandArgs;
}

async function main(): Promise<void> {
  try {
    const args = parseArgs();

    // Get required environment variables
    const githubToken = process.env.GITHUB_TOKEN;

    if (!githubToken) {
      console.error("❌ GITHUB_TOKEN environment variable is required");
      process.exit(1);
    }

    // Initialize components
    const githubApi = new GitHubAPI(githubToken, args.repoOwner, args.repoName);
    const aiProcessor = new AICommandProcessor(githubToken);

    // Check user permissions first
    const isAuthorized = await githubApi.checkUserPermissions(args.commentUser);
    if (!isAuthorized) {
      await githubApi.replyToComment(
        args.prNumber,
        args.commentId,
        "❌ Only maintainers and collaborators can use the `/ai` command."
      );
      return;
    }

    // Extract the AI command text
    const commandText = aiProcessor.extractCommandText(args.commentBody);
    if (!commandText) {
      await githubApi.replyToComment(
        args.prNumber,
        args.commentId,
        "❌ Please provide a question or request after `/ai`. Example: `/ai Can you simplify this function?`"
      );
      return;
    }

    // Get code context (either file content or diff based on subject type)
    let codeContext: string;
    let isFileDiff = false;

    if (args.subjectType === "file") {
      // For file-level comments, get the git diff
      const fileDiff = await githubApi.getFileDiff(
        args.filePath,
        args.commitSha,
        args.prNumber
      );

      if (fileDiff) {
        codeContext = fileDiff;
        isFileDiff = true;
      } else {
        // Fallback to file content if diff is not available
        const fileContent = await githubApi.getFileContent(
          args.filePath,
          args.commitSha
        );
        if (!fileContent) {
          await githubApi.replyToComment(
            args.prNumber,
            args.commentId,
            `❌ Could not retrieve content for file: ${args.filePath}`
          );
          return;
        }
        codeContext = aiProcessor.getCodeContext(
          fileContent,
          args.lineNumber,
          args.startLineNumber,
          args.subjectType
        );
      }
    } else {
      // For line-level comments, get file content and extract context
      const fileContent = await githubApi.getFileContent(
        args.filePath,
        args.commitSha
      );
      if (!fileContent) {
        await githubApi.replyToComment(
          args.prNumber,
          args.commentId,
          `❌ Could not retrieve content for file: ${args.filePath}`
        );
        return;
      }
      codeContext = aiProcessor.getCodeContext(
        fileContent,
        args.lineNumber,
        args.startLineNumber,
        args.subjectType
      );
    }

    // Get thread context
    const threadContext = await githubApi.getCommentThread(
      args.prNumber,
      args.commentId
    );

    // Build messages and generate response
    const messages = aiProcessor.buildMessages(
      commandText,
      args.filePath,
      codeContext,
      threadContext,
      isFileDiff
    );
    const aiResponse = await aiProcessor.generateResponse(messages);

    // Add AI attribution with user mention
    const responseBody = `@${args.commentUser} ${aiResponse}\n\n---\n*🤖 Generated by AI assistant*`;

    // Reply to the comment
    const success = await githubApi.replyToComment(
      args.prNumber,
      args.commentId,
      responseBody
    );

    if (success) {
      console.log("✅ AI response posted successfully");
    } else {
      console.error("❌ Failed to post AI response");
      process.exit(1);
    }
  } catch (error) {
    const errorMsg = `❌ Error processing AI command: ${
      error instanceof Error ? error.message : String(error)
    }`;
    console.error(errorMsg);

    // Try to post error message if we have enough context
    try {
      const args = parseArgs();
      const githubToken = process.env.GITHUB_TOKEN;
      if (githubToken) {
        const githubApi = new GitHubAPI(
          githubToken,
          args.repoOwner,
          args.repoName
        );
        await githubApi.replyToComment(args.prNumber, args.commentId, errorMsg);
      }
    } catch {
      // Ignore errors in error handling
    }

    process.exit(1);
  }
}

// Run the main function
main().catch(console.error);
