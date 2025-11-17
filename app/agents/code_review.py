"""Code Review Agent for security analysis and code quality review."""

from typing import Dict, Any, Optional
from app.agents.base import BaseAgent
from app.models.agent import AgentResult
from app.llm.base import LLMProvider


class CodeReviewAgent(BaseAgent):
    """Agent specialized in code review and security analysis."""

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize the Code Review Agent.

        Args:
            llm_provider: LLM provider instance
        """
        super().__init__(
            agent_id="code_review",
            name="Code Review Agent",
            description="Performs security analysis, code quality review, and vulnerability detection",
            llm_provider=llm_provider,
            capabilities=[
                "security_analysis",
                "vulnerability_detection",
                "code_quality_review",
                "static_analysis",
                "best_practices_check",
                "dependency_analysis"
            ]
        )

    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        Execute a code review task.

        Args:
            task: Code review task description
            context: Optional context (e.g., file_path, directory, focus_areas)

        Returns:
            AgentResult with review results
        """
        try:
            context = context or {}
            
            # Determine review scope
            file_path = context.get("file_path")
            directory = context.get("directory", ".")
            focus_areas = context.get("focus_areas", ["security", "quality"])
            
            # Collect code information using tools
            code_info = await self._collect_code_info(file_path, directory, focus_areas)
            
            # Use dynamic prompt generation with code info as project analysis
            from app.core.prompt_generator import get_prompt_generator
            prompt_gen = get_prompt_generator()
            
            # Enhance context with focus areas
            enhanced_context = {**context, "security_focus": "security" in focus_areas}
            
            # Use code_info as project_analysis
            project_analysis = {
                "structure": code_info.get("structure", []),
                "files_analyzed": len(code_info.get("files_analyzed", []))
            }
            
            prompts = prompt_gen.generate_agent_prompt(
                agent_id=self.agent_id,
                task=task,
                context=enhanced_context,
                project_analysis=project_analysis
            )
            system_prompt = prompts["system_prompt"]
            
            # Build user prompt with code information (more detailed than base prompt)
            user_prompt = self._build_user_prompt(task, code_info, context)
            
            # Generate response using LLM
            response = await self._generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2  # Lower temperature for more focused technical analysis
            )
            
            # Format output
            output = {
                "summary": response[:300] + "..." if len(response) > 300 else response,
                "full_analysis": response,
                "review_type": self._identify_review_type(task, focus_areas),
                "files_analyzed": code_info.get("files_analyzed", []),
                "issues_found": self._extract_issues(response),
                "recommendations": self._extract_recommendations(response),
                "code_info": code_info
            }
            
            return self._format_result(
                success=True,
                output=output,
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "files_count": len(code_info.get("files_analyzed", [])),
                    "focus_areas": focus_areas
                }
            )
            
        except Exception as e:
            return self._format_result(
                success=False,
                output={},
                error=f"Code review failed: {str(e)}",
                metadata={
                    "agent_id": self.agent_id,
                    "task": task
                }
            )
    
    async def _collect_code_info(
        self,
        file_path: Optional[str],
        directory: str,
        focus_areas: list
    ) -> Dict[str, Any]:
        """
        Collect code information using tools.
        
        Args:
            file_path: Optional specific file to analyze
            directory: Directory to analyze
            focus_areas: Areas to focus on
            
        Returns:
            Dictionary with code information
        """
        code_info = {
            "files_analyzed": [],
            "structure": {},
            "patterns": []
        }
        
        try:
            # List directory structure
            dir_result = await self.use_tool("directory_list", {
                "directory": directory,
                "max_depth": 2
            })
            code_info["structure"] = dir_result.get("entries", [])
            
            # If specific file provided, read it
            if file_path:
                try:
                    file_result = await self.use_tool("file_read", {
                        "file_path": file_path
                    })
                    code_info["files_analyzed"].append({
                        "path": file_path,
                        "content": file_result.get("content", ""),
                        "size": file_result.get("size", 0),
                        "lines": file_result.get("lines", 0)
                    })
                except Exception as e:
                    # File read failed, continue with other analysis
                    pass
            
            # Search for security patterns if security is a focus
            if "security" in focus_areas:
                security_patterns = [
                    r"eval\s*\(",
                    r"exec\s*\(",
                    r"__import__\s*\(",
                    r"subprocess\.",
                    r"os\.system\s*\(",
                    r"shell=True",
                    r"SQL.*\+.*%",
                    r"password\s*=\s*['\"]",
                    r"api[_-]?key\s*=\s*['\"]",
                    r"secret\s*=\s*['\"]"
                ]
                
                for pattern in security_patterns:
                    try:
                        search_result = await self.use_tool("code_search", {
                            "pattern": pattern,
                            "directory": directory,
                            "file_pattern": "*.py"
                        })
                        if search_result.get("count", 0) > 0:
                            code_info["patterns"].append({
                                "type": "security_pattern",
                                "pattern": pattern,
                                "matches": search_result.get("results", [])[:10]  # Limit results
                            })
                    except Exception:
                        continue
            
            # Search for quality patterns
            if "quality" in focus_areas:
                quality_patterns = [
                    r"TODO|FIXME|XXX|HACK",
                    r"except\s*:",
                    r"print\s*\(",
                    r"import\s+\*"
                ]
                
                for pattern in quality_patterns:
                    try:
                        search_result = await self.use_tool("code_search", {
                            "pattern": pattern,
                            "directory": directory,
                            "file_pattern": "*.py"
                        })
                        if search_result.get("count", 0) > 0:
                            code_info["patterns"].append({
                                "type": "quality_pattern",
                                "pattern": pattern,
                                "matches": search_result.get("results", [])[:10]
                            })
                    except Exception:
                        continue
            
        except Exception as e:
            # Tool execution failed, continue with LLM analysis
            code_info["error"] = f"Tool execution error: {str(e)}"
        
        return code_info
    
    def _build_system_prompt(self, focus_areas: list) -> str:
        """Build system prompt based on focus areas."""
        base_prompt = """You are an expert code reviewer specializing in security analysis and code quality.
Analyze code for vulnerabilities, security issues, and quality problems. Provide specific, actionable recommendations."""
        
        if "security" in focus_areas:
            base_prompt += """
        
Security Focus Areas:
- SQL injection vulnerabilities
- Command injection risks
- Authentication and authorization issues
- Sensitive data exposure
- Insecure dependencies
- Input validation problems
- Cryptographic weaknesses"""
        
        if "quality" in focus_areas:
            base_prompt += """
        
Quality Focus Areas:
- Code maintainability
- Best practices violations
- Error handling
- Code duplication
- Performance issues
- Documentation gaps"""
        
        return base_prompt
    
    def _build_user_prompt(
        self,
        task: str,
        code_info: Dict[str, Any],
        context: Dict[str, Any]
    ) -> str:
        """Build user prompt with code information."""
        prompt = f"Code Review Task: {task}\n\n"
        
        # Add file information
        if code_info.get("files_analyzed"):
            prompt += "Files to Review:\n"
            for file_info in code_info["files_analyzed"]:
                prompt += f"- {file_info['path']} ({file_info['lines']} lines)\n"
                # Include first 50 lines of code for context
                content_lines = file_info.get("content", "").splitlines()[:50]
                prompt += "Code:\n```\n" + "\n".join(content_lines) + "\n```\n\n"
        
        # Add pattern matches
        if code_info.get("patterns"):
            prompt += "Pattern Matches Found:\n"
            for pattern_info in code_info["patterns"]:
                prompt += f"\n{pattern_info['type']}: {pattern_info['pattern']}\n"
                for match in pattern_info.get("matches", [])[:5]:
                    prompt += f"  - {match['file']}:{match['line']}: {match['content']}\n"
        
        # Add directory structure
        if code_info.get("structure"):
            prompt += f"\nProject Structure (showing {len(code_info['structure'])} entries):\n"
            for entry in code_info["structure"][:20]:  # Limit structure display
                prompt += f"- {entry['type']}: {entry['path']}\n"
        
        prompt += """
Please provide:
1. Security vulnerabilities found (if any)
2. Code quality issues
3. Specific recommendations with code examples
4. Priority levels (Critical, High, Medium, Low)
5. Best practices suggestions"""
        
        return prompt
    
    def _identify_review_type(self, task: str, focus_areas: list) -> str:
        """Identify the type of code review needed."""
        task_lower = task.lower()
        
        if any(keyword in task_lower for keyword in ['security', 'vulnerability', 'exploit', 'attack']):
            return "security_review"
        elif any(keyword in task_lower for keyword in ['quality', 'maintainability', 'refactor']):
            return "quality_review"
        elif any(keyword in task_lower for keyword in ['performance', 'optimization', 'speed']):
            return "performance_review"
        elif "security" in focus_areas and "quality" in focus_areas:
            return "comprehensive_review"
        else:
            return "general_review"
    
    def _extract_issues(self, response: str) -> list:
        """Extract issues from LLM response (simple extraction)."""
        issues = []
        lines = response.splitlines()
        
        for i, line in enumerate(lines):
            if any(keyword in line.lower() for keyword in ['vulnerability', 'issue', 'problem', 'bug', 'risk']):
                # Try to extract issue description
                if i + 1 < len(lines):
                    issues.append({
                        "type": "issue",
                        "description": line.strip(),
                        "context": lines[i+1].strip() if i+1 < len(lines) else ""
                    })
        
        return issues[:10]  # Limit issues
    
    def _extract_recommendations(self, response: str) -> list:
        """Extract recommendations from LLM response."""
        recommendations = []
        lines = response.splitlines()
        
        for i, line in enumerate(lines):
            if any(keyword in line.lower() for keyword in ['recommend', 'suggest', 'should', 'consider']):
                recommendations.append({
                    "type": "recommendation",
                    "description": line.strip()
                })
        
        return recommendations[:10]  # Limit recommendations

