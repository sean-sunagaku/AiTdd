"""Agent adapters used by the TDD loop."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

CODEX_SDK_BRIDGE = r"""
import { Codex } from "@openai/codex-sdk";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

const input = JSON.parse(await readStdin());
const codex = new Codex();
const thread = codex.startThread({
  workingDirectory: input.cwd,
  skipGitRepoCheck: true,
  sandboxMode: "read-only",
  approvalPolicy: "never",
  model: input.model || undefined,
});
const turnOptions = {};
if (input.outputSchema) {
  turnOptions.outputSchema = input.outputSchema;
}
const result = await thread.run(input.prompt, turnOptions);
process.stdout.write(JSON.stringify({
  status: "finished",
  result: result.finalResponse,
  usage: result.usage,
  threadId: thread.id,
}) + "\n");
"""

CURSOR_SDK_BRIDGE = r"""
import { Agent } from "@cursor/sdk";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

const input = JSON.parse(await readStdin());
const options = {
  model: { id: input.model || "composer-latest" },
  local: {
    cwd: input.cwd,
    sandboxOptions: { enabled: false },
  },
};
if (process.env.CURSOR_API_KEY) {
  options.apiKey = process.env.CURSOR_API_KEY;
}
const result = await Agent.prompt(input.prompt, options);
process.stdout.write(JSON.stringify({
  status: result.status,
  result: result.result ?? "",
  durationMs: result.durationMs,
}) + "\n");
"""


@dataclass(frozen=True)
class AgentResult:
    role: str
    prompt: str
    stdout: str
    stderr: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Agent(Protocol):
    role: str

    def run(
        self,
        prompt: str,
        cwd: Path,
        output_schema: dict[str, object] | None = None,
    ) -> AgentResult:
        """Run the agent for one prompt."""


@dataclass(frozen=True)
class DryRunAgent:
    role: str

    def run(
        self,
        prompt: str,
        cwd: Path,
        output_schema: dict[str, object] | None = None,
    ) -> AgentResult:
        return AgentResult(
            role=self.role,
            prompt=prompt,
            stdout=f"[dry-run:{self.role}] cwd={cwd}\n{prompt}\n",
            stderr="",
            returncode=0,
        )


@dataclass(frozen=True)
class CodexSdkAgent:
    """Codex planning/review adapter using the official @openai/codex-sdk."""

    role: str = "codex"
    model: str | None = None
    timeout: int = 900
    node_bin: str = "node"

    def run(
        self,
        prompt: str,
        cwd: Path,
        output_schema: dict[str, object] | None = None,
    ) -> AgentResult:
        command = [
            self.node_bin,
            "--input-type=module",
            "-e",
            CODEX_SDK_BRIDGE,
        ]
        completed = subprocess.run(
            command,
            cwd=_node_package_root(cwd),
            input=json.dumps(
                {
                    "cwd": str(cwd),
                    "model": self.model,
                    "prompt": prompt,
                    "outputSchema": output_schema,
                }
            ),
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        return AgentResult(
            self.role,
            prompt,
            _result_text(completed.stdout),
            completed.stderr,
            completed.returncode,
        )


@dataclass(frozen=True)
class CursorCliAgent:
    """Cursor implementation adapter using Cursor Agent CLI with Composer."""

    role: str = "cursor"
    cursor_bin: str = "cursor-agent"
    model: str | None = "composer-latest"
    timeout: int = 1800
    force: bool = True

    def run(self, prompt: str, cwd: Path) -> AgentResult:
        command = [
            self.cursor_bin,
            "--print",
            "--output-format",
            "text",
            "--trust",
            "--workspace",
            str(cwd),
        ]
        if self.force:
            command.append("--force")
        if self.model:
            command.extend(["--model", self.model])
        command.append(prompt)
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
            env=_cursor_sdk_env(),
        )
        return AgentResult(
            self.role,
            prompt,
            completed.stdout,
            completed.stderr,
            completed.returncode,
        )


@dataclass(frozen=True)
class CursorSdkAgent:
    """Cursor implementation adapter using the official @cursor/sdk."""

    role: str = "cursor"
    model: str = "composer-latest"
    timeout: int = 1800
    node_bin: str = "node"

    def run(self, prompt: str, cwd: Path) -> AgentResult:
        command = [
            self.node_bin,
            "--input-type=module",
            "-e",
            CURSOR_SDK_BRIDGE,
        ]
        completed = subprocess.run(
            command,
            cwd=_node_package_root(cwd),
            input=json.dumps({"cwd": str(cwd), "model": self.model, "prompt": prompt}),
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
            env=_cursor_sdk_env(),
        )
        return AgentResult(
            self.role,
            prompt,
            _result_text(completed.stdout),
            _friendly_cursor_sdk_stderr(completed.stderr),
            completed.returncode,
        )


def _friendly_cursor_sdk_stderr(stderr: str) -> str:
    if "AuthenticationError" not in stderr:
        return stderr
    return (
        "Cursor SDK authentication failed. "
        "Set CURSOR_API_KEY or make sure the official @cursor/sdk can resolve Cursor auth. "
        "Original stderr follows:\n"
        f"{stderr}"
    )


def _node_package_root(workdir: Path) -> Path:
    if (workdir / "node_modules" / "@cursor" / "sdk").exists():
        return workdir
    return Path(__file__).resolve().parents[2]


def _cursor_sdk_env() -> dict[str, str]:
    env = os.environ.copy()
    if env.get("CURSOR_API_KEY"):
        return env

    token = _read_macos_keychain_secret("aitdd.cursor_api_key")
    if token:
        env["CURSOR_API_KEY"] = token
    return env


def _read_macos_keychain_secret(service: str) -> str | None:
    completed = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", service],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    token = completed.stdout.strip()
    return token or None


def _result_text(stdout: str) -> str:
    value = parse_json_object(stdout)
    result = value.get("result")
    return result if isinstance(result, str) else stdout


def parse_json_object(text: str) -> dict[str, object]:
    """Parse the first JSON object from an agent response."""

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
