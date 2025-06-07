#!/usr/bin/env node
"use strict";
/**
 * AI Command Handler for GitHub Pull Request Reviews
 *
 * This script processes /ai commands in PR review comments and responds with AI-generated suggestions.
 */
class GitHubAPI {
    constructor(token, repoOwner, repoName) {
        this.baseUrl = "https://api.github.com";
        this.token = token;
        this.repoOwner = repoOwner;
        this.repoName = repoName;
    }
    get headers() {
        return {
            Authorization: `Bearer ${this.token}`,
            Accept: "application/vnd.github.v3+json",
            "User-Agent": "MLflow-AI-Command",
            "Content-Type": "application/json",
        };
    }
    async getFileContent(filePath, commitSha) {
        try {
            const url = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/contents/${filePath}`;
            const params = new URLSearchParams({ ref: commitSha });
            const response = await fetch(`${url}?${params}`, {
                headers: this.headers,
            });
            if (!response.ok) {
                console.error(`Failed to fetch file content: ${response.status} ${response.statusText}`);
                return null;
            }
            const data = (await response.json());
            if (data.encoding === "base64") {
                return Buffer.from(data.content, "base64").toString("utf-8");
            }
            return data.content;
        }
        catch (error) {
            console.error("Error fetching file content:", error);
            return null;
        }
    }
    async getCommentThread(prNumber, commentId) {
        try {
            const url = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/pulls/${prNumber}/comments`;
            const response = await fetch(url, {
                headers: this.headers,
            });
            if (!response.ok) {
                console.error(`Failed to fetch comments: ${response.status} ${response.statusText}`);
                return [];
            }
            const comments = (await response.json());
            // Find the target comment
            const targetComment = comments.find(comment => comment.id === commentId);
            if (!targetComment) {
                return [];
            }
            // Find all comments in the same thread (same line, same file)
            const threadComments = comments.filter(comment => comment.path === targetComment.path &&
                comment.line === targetComment.line &&
                comment.original_line === targetComment.original_line);
            // Sort by creation time
            return threadComments.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
        }
        catch (error) {
            console.error("Error fetching comment thread:", error);
            return [];
        }
    }
    async replyToComment(prNumber, commentId, body) {
        try {
            // First get the original comment to extract necessary info for reply
            const commentUrl = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/pulls/comments/${commentId}`;
            const commentResponse = await fetch(commentUrl, {
                headers: this.headers,
            });
            if (!commentResponse.ok) {
                console.error(`Failed to fetch original comment: ${commentResponse.status} ${commentResponse.statusText}`);
                return false;
            }
            const originalComment = (await commentResponse.json());
            // Create a new review comment in reply
            const url = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/pulls/${prNumber}/comments`;
            const data = {
                body,
                commit_id: originalComment.commit_id,
                path: originalComment.path,
                line: originalComment.line || originalComment.original_line,
                in_reply_to: commentId,
            };
            const response = await fetch(url, {
                method: "POST",
                headers: this.headers,
                body: JSON.stringify(data),
            });
            return response.status === 201;
        }
        catch (error) {
            console.error("Error replying to comment:", error);
            return false;
        }
    }
    async checkUserPermissions(username) {
        try {
            const url = `${this.baseUrl}/repos/${this.repoOwner}/${this.repoName}/collaborators/${username}/permission`;
            const response = await fetch(url, {
                headers: this.headers,
            });
            if (!response.ok) {
                console.error(`Failed to check permissions: ${response.status} ${response.statusText}`);
                return false;
            }
            const data = (await response.json());
            const isAuthorized = ["admin", "write"].includes(data.permission);
            console.log(`User ${username} has permission: ${data.permission}, authorized: ${isAuthorized}`);
            return isAuthorized;
        }
        catch (error) {
            console.error("Error checking user permissions:", error);
            return false;
        }
    }
}
class AICommandProcessor {
    constructor(githubToken) {
        this.githubToken = githubToken;
    }
    extractCommandText(commentBody) {
        const lines = commentBody.trim().split("\n");
        for (const line of lines) {
            const trimmedLine = line.trim();
            if (trimmedLine.startsWith("/ai")) {
                // Remove '/ai' and return the rest
                return trimmedLine.slice(3).trim();
            }
        }
        return "";
    }
    getCodeContext(fileContent, lineNumber, contextLines = 5) {
        if (!fileContent || !lineNumber) {
            return fileContent || "";
        }
        const lines = fileContent.split("\n");
        const totalLines = lines.length;
        // Calculate context range
        const start = Math.max(0, lineNumber - contextLines - 1); // lineNumber is 1-indexed
        const end = Math.min(totalLines, lineNumber + contextLines);
        const contextLinesList = [];
        for (let i = start; i < end; i++) {
            const prefix = i === lineNumber - 1 ? ">>> " : "    ";
            contextLinesList.push(`${prefix}${(i + 1).toString().padStart(4)}: ${lines[i]}`);
        }
        return contextLinesList.join("\n");
    }
    buildPrompt(commandText, filePath, codeContext, threadContext) {
        const promptParts = [
            "You are an expert code reviewer helping with a GitHub pull request.",
            `File: ${filePath}`,
            "",
            "Code context:",
            "```",
            codeContext,
            "```",
            "",
            `User request: ${commandText}`,
        ];
        // Add thread context if available
        if (threadContext.length > 1) {
            promptParts.push("", "Previous discussion in this thread:");
            // Exclude the current comment
            for (const comment of threadContext.slice(0, -1)) {
                promptParts.push(`@${comment.user.login}: ${comment.body}`);
            }
        }
        promptParts.push("", "Please provide a helpful response. Keep it concise and focused on the specific request.", "If suggesting code changes, use proper markdown formatting with code blocks.");
        return promptParts.join("\n");
    }
    async generateResponse(prompt) {
        try {
            const response = await fetch("https://models.github.ai/inference/chat/completions", {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${this.githubToken}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    model: "openai/gpt-4o",
                    messages: [
                        {
                            role: "system",
                            content: "You are a helpful code reviewer assistant.",
                        },
                        {
                            role: "user",
                            content: prompt,
                        },
                    ],
                    max_tokens: 1000,
                    temperature: 0.7,
                    top_p: 1.0,
                }),
            });
            if (!response.ok) {
                throw new Error(`API request failed: ${response.status} ${response.statusText}`);
            }
            const data = (await response.json());
            return (data.choices[0]?.message?.content?.trim() || "❌ No response generated");
        }
        catch (error) {
            console.error("Error generating AI response:", error);
            return `❌ Error generating AI response: ${error instanceof Error ? error.message : String(error)}`;
        }
    }
}
function parseArgs() {
    const args = process.argv.slice(2);
    const parsed = {};
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
    const required = [
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
            throw new Error(`Missing required argument: --${field
                .replace(/([A-Z])/g, "-$1")
                .toLowerCase()}`);
        }
    }
    return parsed;
}
async function main() {
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
            await githubApi.replyToComment(args.prNumber, args.commentId, "❌ Only maintainers and collaborators can use the `/ai` command.");
            return;
        }
        // Extract the AI command text
        const commandText = aiProcessor.extractCommandText(args.commentBody);
        if (!commandText) {
            await githubApi.replyToComment(args.prNumber, args.commentId, "❌ Please provide a question or request after `/ai`. Example: `/ai Can you simplify this function?`");
            return;
        }
        // Get file content
        const fileContent = await githubApi.getFileContent(args.filePath, args.commitSha);
        if (!fileContent) {
            await githubApi.replyToComment(args.prNumber, args.commentId, `❌ Could not retrieve content for file: ${args.filePath}`);
            return;
        }
        // Get code context
        const codeContext = aiProcessor.getCodeContext(fileContent, args.lineNumber);
        // Get thread context
        const threadContext = await githubApi.getCommentThread(args.prNumber, args.commentId);
        // Build prompt and generate response
        const prompt = aiProcessor.buildPrompt(commandText, args.filePath, codeContext, threadContext);
        const aiResponse = await aiProcessor.generateResponse(prompt);
        // Add AI attribution
        const responseBody = `${aiResponse}\n\n---\n*🤖 Generated by AI assistant*`;
        // Reply to the comment
        const success = await githubApi.replyToComment(args.prNumber, args.commentId, responseBody);
        if (success) {
            console.log("✅ AI response posted successfully");
        }
        else {
            console.error("❌ Failed to post AI response");
            process.exit(1);
        }
    }
    catch (error) {
        const errorMsg = `❌ Error processing AI command: ${error instanceof Error ? error.message : String(error)}`;
        console.error(errorMsg);
        // Try to post error message if we have enough context
        try {
            const args = parseArgs();
            const githubToken = process.env.GITHUB_TOKEN;
            if (githubToken) {
                const githubApi = new GitHubAPI(githubToken, args.repoOwner, args.repoName);
                await githubApi.replyToComment(args.prNumber, args.commentId, errorMsg);
            }
        }
        catch {
            // Ignore errors in error handling
        }
        process.exit(1);
    }
}
// Run the main function
main().catch(console.error);
