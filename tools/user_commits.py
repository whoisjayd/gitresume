"""
User-specific commit analysis tool.

This module provides functionality to analyze only the commits and code
contributions made by the authenticated GitHub user, allowing for
personalized resume content generation based on individual contributions.
"""

import subprocess
import json
import os
import logging
import shlex
from pathlib import Path
from typing import List, Dict, Set, Optional
from github import Github, GithubException

logger = logging.getLogger(__name__)


def safe_git_command(cmd_args: List[str], repo_path: str, check: bool = True) -> subprocess.CompletedProcess:
    """
    Execute a git command safely with proper validation and error handling.
    
    Args:
        cmd_args: List of command arguments (must start with 'git')
        repo_path: Repository path (validated to be safe)
        check: Whether to raise exception on non-zero exit code
        
    Returns:
        CompletedProcess result
        
    Raises:
        ValueError: If command or path is invalid
        subprocess.CalledProcessError: If command fails and check=True
    """
    # Validate command starts with git
    if not cmd_args or cmd_args[0] != 'git':
        raise ValueError("Command must start with 'git'")
    
    # Validate and sanitize repository path
    repo_path_obj = Path(repo_path).resolve()
    if not repo_path_obj.exists() or not (repo_path_obj / '.git').exists():
        raise ValueError(f"Invalid repository path: {repo_path_obj}")
    
    # Ensure all arguments are strings and safe
    safe_args = []
    for arg in cmd_args:
        if not isinstance(arg, str):
            raise ValueError(f"All command arguments must be strings, got: {type(arg)}")
        # Basic validation - no shell metacharacters in git arguments
        if any(char in arg for char in ['&', '|', ';', '$', '`', '\n', '\r']):
            raise ValueError(f"Invalid characters in git argument: {arg}")
        safe_args.append(arg)
    
    logger.debug(f"Executing safe git command: {' '.join(safe_args)} in {repo_path_obj}")
    
    return subprocess.run(
        safe_args,
        cwd=str(repo_path_obj),
        capture_output=True,
        text=True,
        check=check,
        timeout=30  # Add timeout for security
    )


class UserCommitAnalyzer:
    """Analyzes commits and contributions made by a specific GitHub user."""
    
    def __init__(self, github_token: str):
        """
        Initialize the analyzer with a GitHub token.
        
        Args:
            github_token: Valid GitHub personal access token
        """
        self.github = Github(github_token)
        try:
            self.user = self.github.get_user()
            self.user_login = self.user.login
            logger.info(f"Initialized UserCommitAnalyzer for user: {self.user_login}")
        except GithubException as e:
            logger.error(f"Failed to authenticate with GitHub: {e}")
            raise ValueError("Invalid GitHub token or API error") from e
        
    def get_user_emails(self) -> Set[str]:
        """
        Get all email addresses associated with the authenticated user.
        
        Returns:
            Set of email addresses associated with the user
        """
        emails = set()
        
        try:
            # Get all user emails from GitHub API
            user_emails = self.user.get_emails()
            for email_obj in user_emails:
                emails.add(email_obj.email.lower())
            logger.debug(f"Found {len(emails)} email addresses for user")
        except Exception as e:
            logger.warning(f"Could not fetch user emails: {e}")
            
        return emails
    
    def get_user_commits(self, repo_path: str) -> List[str]:
        """
        Get commit hashes for commits made by the authenticated user.
        
        Args:
            repo_path: Path to the local git repository
            
        Returns:
            List of commit hashes authored by the user
        """
        user_emails = self.get_user_emails()
        commit_hashes = []
        
        try:
            # Get all commits with author information
            cmd = [
                'git', 'log', 
                '--pretty=format:%H|%ae|%an', 
                '--all'
            ]
            
            result = safe_git_command(cmd, repo_path)
            
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                    
                parts = line.split('|')
                if len(parts) >= 3:
                    commit_hash, author_email, author_name = parts[0], parts[1], parts[2]
                    
                    # Check if commit is by the authenticated user
                    if (author_email.lower() in user_emails or
                        author_name.lower() == self.user_login.lower()):
                        commit_hashes.append(commit_hash)
                        
            logger.info(f"Found {len(commit_hashes)} commits by user {self.user_login}")
                        
        except subprocess.CalledProcessError as e:
            logger.error(f"Error getting user commits: {e}")
            
        return commit_hashes
    
    def get_user_modified_files(self, repo_path: str) -> Set[str]:
        """
        Get files that were modified by the authenticated user.
        
        Args:
            repo_path: Path to the local git repository
            
        Returns:
            Set of file paths modified by the user
        """
        user_commits = self.get_user_commits(repo_path)
        modified_files = set()
        
        for commit_hash in user_commits:
            try:
                # Get files modified in this commit
                cmd = [
                    'git', 'diff-tree', 
                    '--no-commit-id', 
                    '--name-only', 
                    '-r', 
                    commit_hash
                ]
                
                result = safe_git_command(cmd, repo_path)
                
                for file_path in result.stdout.strip().split('\n'):
                    if file_path:
                        full_path = os.path.join(repo_path, file_path)
                        if os.path.exists(full_path):
                            modified_files.add(file_path)
                            
            except subprocess.CalledProcessError as e:
                logger.warning(f"Error getting files for commit {commit_hash}: {e}")
        
        logger.info(f"User {self.user_login} modified {len(modified_files)} files")
        return modified_files
    
    def get_user_commit_diffs_via_api(self, repo_url: str, max_commits: int = 10) -> List[Dict[str, str]]:
        """
        Get the actual diff content for user's commits using GitHub API.
        
        Args:
            repo_url: GitHub repository URL (e.g., "https://github.com/owner/repo")
            max_commits: Maximum number of commits to include
        
        Returns:
            List of commit diffs with metadata
        """
        try:
            # Extract owner and repo from URL
            parts = repo_url.replace('https://github.com/', '').split('/')
            owner, repo_name = parts[0], parts[1]
            
            # Get the repository object
            repo = self.github.get_repo(f"{owner}/{repo_name}")
            
            # Get commits by the authenticated user
            commits = repo.get_commits(author=self.user_login)
            
            commit_diffs = []
            count = 0
            
            for commit in commits:
                if count >= max_commits:
                    break
                
                try:
                    # Get detailed commit information including files
                    commit_detail = repo.get_commit(commit.sha)
                    
                    # Build diff content from files
                    diff_content = []
                    total_additions = 0
                    total_deletions = 0
                    
                    for file in commit_detail.files:
                        if file.patch:  # Only if patch/diff is available
                            diff_content.append(f"--- a/{file.filename}")
                            diff_content.append(f"+++ b/{file.filename}")
                            diff_content.append(file.patch)
                            diff_content.append("")
                        
                        total_additions += file.additions
                        total_deletions += file.deletions
                    
                    if diff_content:
                        diff_text = "\n".join(diff_content)
                        
                        # Limit diff size to avoid overwhelming the prompt
                        max_diff_chars = 2000
                        if len(diff_text) > max_diff_chars:
                            diff_text = diff_text[:max_diff_chars] + "\n... [diff truncated]"
                        
                        commit_diffs.append({
                            'hash': commit.sha[:8],
                            'message': commit.commit.message.split('\n')[0],  # First line only
                            'diff': diff_text,
                            'additions': total_additions,
                            'deletions': total_deletions,
                            'files_changed': len(commit_detail.files),
                            'date': commit.commit.author.date.isoformat(),
                            'url': commit.html_url
                        })
                        
                        count += 1
                        
                except GithubException as e:
                    logger.warning(f"Error getting commit details for {commit.sha}: {e}")
                    continue
            
            logger.info(f"Collected {len(commit_diffs)} commit diffs via GitHub API for user {self.user_login}")
            return commit_diffs
            
        except GithubException as e:
            logger.error(f"Error accessing repository via GitHub API: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error getting commit diffs via API: {e}")
            return []
    
    def get_user_commits_via_api(self, repo_url: str) -> List[str]:
        """
        Get user's commit hashes using GitHub API.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            List of commit SHAs authored by the user
        """
        try:
            # Extract owner and repo from URL
            parts = repo_url.replace('https://github.com/', '').split('/')
            owner, repo_name = parts[0], parts[1]
            
            # Get the repository object
            repo = self.github.get_repo(f"{owner}/{repo_name}")
            
            # Get commits by the authenticated user
            commits = repo.get_commits(author=self.user_login)
            
            commit_hashes = [commit.sha for commit in commits]
            
            logger.info(f"Found {len(commit_hashes)} commits by user {self.user_login} via GitHub API")
            return commit_hashes
            
        except GithubException as e:
            logger.error(f"Error getting commits via GitHub API: {e}")
            return []
    
    def get_user_stats_via_api(self, repo_url: str, max_commits: int = 50) -> Dict:
        """
        Get user's contribution statistics using GitHub API.
        
        Args:
            repo_url: GitHub repository URL
            max_commits: Maximum number of commits to analyze
            
        Returns:
            Dictionary containing user's contribution statistics
        """
        try:
            # Extract owner and repo from URL
            parts = repo_url.replace('https://github.com/', '').split('/')
            owner, repo_name = parts[0], parts[1]
            
            # Get the repository object
            repo = self.github.get_repo(f"{owner}/{repo_name}")
            
            # Get commits by the authenticated user
            commits = repo.get_commits(author=self.user_login)
            
            stats = {
                "total_commits": 0,
                "lines_added": 0,
                "lines_deleted": 0,
                "files_modified": 0,
                "languages": set()
            }
            
            count = 0
            for commit in commits:
                if count >= max_commits:
                    break
                    
                try:
                    commit_detail = repo.get_commit(commit.sha)
                    stats["total_commits"] += 1
                    
                    for file in commit_detail.files:
                        stats["lines_added"] += file.additions
                        stats["lines_deleted"] += file.deletions
                        stats["files_modified"] += 1
                        
                        # Extract language from file extension
                        if '.' in file.filename:
                            ext = '.' + file.filename.split('.')[-1].lower()
                            language_map = {
                                '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
                                '.jsx': 'React', '.tsx': 'React', '.html': 'HTML',
                                '.css': 'CSS', '.scss': 'SCSS', '.java': 'Java',
                                '.cpp': 'C++', '.c': 'C', '.h': 'C/C++',
                                '.php': 'PHP', '.rb': 'Ruby', '.go': 'Go',
                                '.rs': 'Rust', '.kt': 'Kotlin', '.swift': 'Swift',
                                '.sql': 'SQL', '.yaml': 'YAML', '.yml': 'YAML',
                                '.json': 'JSON', '.xml': 'XML', '.sh': 'Shell',
                                '.md': 'Markdown'
                            }
                            language = language_map.get(ext, ext.upper().lstrip('.'))
                            stats["languages"].add(language)
                    
                    count += 1
                    
                except GithubException as e:
                    logger.warning(f"Error getting details for commit {commit.sha}: {e}")
                    continue
            
            stats["languages"] = list(stats["languages"])
            
            logger.info(f"User stats via API: {stats['total_commits']} commits, "
                       f"{stats['lines_added']} lines added, "
                       f"{stats['lines_deleted']} lines deleted")
            return stats
            
        except GithubException as e:
            logger.error(f"Error getting user stats via GitHub API: {e}")
            return {"total_commits": 0, "lines_added": 0, "lines_deleted": 0, 
                   "files_modified": 0, "languages": []}
    
    def get_user_commit_diffs(self, repo_path: str, max_commits: int = 10) -> List[Dict[str, str]]:
        """
        Get the actual diff content for user's commits.
        
        Args:
            repo_path: Path to the repository
            max_commits: Maximum number of commits to include (to avoid huge prompts)
        
        Returns:
            List of commit diffs with metadata
        """
        user_commits = self.get_user_commits(repo_path)
        commit_diffs = []
        
        # Limit to recent commits to avoid overwhelming the prompt
        recent_commits = user_commits[:max_commits]
        
        for commit_hash in recent_commits:
            try:
                # Get commit message
                cmd_msg = ['git', 'log', '--format=%s', '-n', '1', commit_hash]
                msg_result = safe_git_command(cmd_msg, repo_path)
                commit_message = msg_result.stdout.strip()
                
                # Get commit diff (exclude binary files and limit size)
                cmd_diff = [
                    'git', 'show', commit_hash, 
                    '--format=', 
                    '--no-merges',
                    '--ignore-space-at-eol',
                    '--unified=3'  # 3 lines of context
                ]
                
                diff_result = safe_git_command(cmd_diff, repo_path)
                
                diff_content = diff_result.stdout.strip()
                
                # Limit diff size to avoid overwhelming the prompt
                max_diff_chars = 2000
                if len(diff_content) > max_diff_chars:
                    diff_content = diff_content[:max_diff_chars] + "\n... [diff truncated]"
                
                # Skip empty diffs or very large binary changes
                if diff_content and len(diff_content) > 10:
                    commit_diffs.append({
                        'hash': commit_hash[:8],  # Short hash
                        'message': commit_message,
                        'diff': diff_content
                    })
                    
            except subprocess.CalledProcessError as e:
                logger.warning(f"Error getting diff for commit {commit_hash}: {e}")
        
        logger.info(f"Collected {len(commit_diffs)} commit diffs for user {self.user_login}")
        return commit_diffs
    
    def get_user_code_stats(self, repo_path: str) -> Dict:
        """
        Get code statistics for user's contributions.
        
        Args:
            repo_path: Path to the local git repository
            
        Returns:
            Dictionary containing user's contribution statistics
        """
        user_commits = self.get_user_commits(repo_path)
        
        stats = {
            "total_commits": len(user_commits),
            "lines_added": 0,
            "lines_deleted": 0,
            "files_modified": 0,
            "languages": set()
        }
        
        for commit_hash in user_commits:
            try:
                # Get commit stats
                cmd = [
                    'git', 'show', 
                    '--stat', 
                    '--format=', 
                    commit_hash
                ]
                
                result = safe_git_command(cmd, repo_path)
                
                # Parse the output to extract stats
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if 'insertion' in line or 'deletion' in line:
                        parts = line.split(',')
                        for part in parts:
                            part = part.strip()
                            if 'insertion' in part:
                                try:
                                    additions = int(part.split()[0])
                                    stats["lines_added"] += additions
                                except (ValueError, IndexError):
                                    pass
                            elif 'deletion' in part:
                                try:
                                    deletions = int(part.split()[0])
                                    stats["lines_deleted"] += deletions
                                except (ValueError, IndexError):
                                    pass
                    elif '|' in line and ('+' in line or '-' in line):
                        # File modification line
                        stats["files_modified"] += 1
                        file_name = line.split('|')[0].strip()
                        ext = os.path.splitext(file_name)[1].lower()
                        if ext:
                            # Map common extensions to language names
                            language_map = {
                                '.py': 'Python',
                                '.js': 'JavaScript', 
                                '.jsx': 'React/JSX',
                                '.ts': 'TypeScript',
                                '.tsx': 'React/TypeScript',
                                '.java': 'Java',
                                '.cpp': 'C++',
                                '.c': 'C',
                                '.cs': 'C#',
                                '.go': 'Go',
                                '.rs': 'Rust',
                                '.php': 'PHP',
                                '.rb': 'Ruby',
                                '.html': 'HTML',
                                '.css': 'CSS',
                                '.scss': 'SCSS',
                                '.sql': 'SQL',
                                '.yaml': 'YAML',
                                '.yml': 'YAML',
                                '.json': 'JSON',
                                '.xml': 'XML',
                                '.sh': 'Shell',
                                '.md': 'Markdown'
                            }
                            language = language_map.get(ext, ext.upper().lstrip('.'))
                            stats["languages"].add(language)
                            
            except subprocess.CalledProcessError as e:
                logger.warning(f"Error getting stats for commit {commit_hash}: {e}")
        
        stats["languages"] = list(stats["languages"])
        logger.info(f"User stats: {stats['total_commits']} commits, "
                   f"{stats['lines_added']} lines added, "
                   f"{stats['lines_deleted']} lines deleted")
        return stats


def filter_repo_by_user_commits(repo_path: str, github_token: str, repo_url: Optional[str] = None) -> Dict:
    """
    Filter repository analysis to include only user's contributions.
    
    Args:
        repo_path: Path to the local git repository (for fallback)
        github_token: Valid GitHub personal access token
        repo_url: GitHub repository URL (preferred method)
        
    Returns:
        Dictionary containing user-specific analysis data
    """
    try:
        analyzer = UserCommitAnalyzer(github_token)
        
        # Prefer GitHub API if repo_url is provided
        if repo_url:
            logger.info(f"Using GitHub API to analyze user commits for {repo_url}")
            
            # Get user's commit data via GitHub API
            commit_diffs = analyzer.get_user_commit_diffs_via_api(repo_url, max_commits=8)
            user_stats = analyzer.get_user_stats_via_api(repo_url, max_commits=50)
            user_commits = analyzer.get_user_commits_via_api(repo_url)
            
            # For user_files, we'll extract from the commit diffs
            user_files = set()
            for commit in commit_diffs:
                # Extract filenames from diff content
                lines = commit.get('diff', '').split('\n')
                for line in lines:
                    if line.startswith('--- a/') or line.startswith('+++ b/'):
                        filename = line.split('/', 1)[1] if '/' in line else ''
                        if filename and filename != '/dev/null':
                            user_files.add(filename)
            
            result = {
                "user_files": list(user_files),
                "user_stats": user_stats,
                "commit_diffs": commit_diffs,
                "total_user_commits": len(user_commits),
                "user_login": analyzer.user_login,
                "analysis_method": "github_api"
            }
        else:
            logger.info(f"Using local Git commands to analyze user commits for {repo_path}")
            
            # Fallback to local Git commands
            user_files = analyzer.get_user_modified_files(repo_path)
            user_stats = analyzer.get_user_code_stats(repo_path)
            commit_diffs = analyzer.get_user_commit_diffs(repo_path, max_commits=8)
            
            result = {
                "user_files": list(user_files),
                "user_stats": user_stats,
                "commit_diffs": commit_diffs,
                "total_user_commits": len(analyzer.get_user_commits(repo_path)),
                "user_login": analyzer.user_login,
                "analysis_method": "local_git"
            }
        
        logger.info(f"User analysis complete: {result['total_user_commits']} commits, "
                   f"{len(result['user_files'])} files, "
                   f"method: {result['analysis_method']}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error filtering repository by user commits: {e}")
        raise
