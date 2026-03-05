"""
Slack and Microsoft Teams bot integration.

Listens for slash commands or @mentions and dispatches them to the orchestrator,
posting results back to the originating channel.

Slack setup:
  1. Create a Slack App at https://api.slack.com/apps
  2. Add slash command /orchestrate pointing to POST /api/v1/integrations/slack/command
  3. Enable Events API with POST /api/v1/integrations/slack/events (for @mentions)
  4. Set SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET in your .env

Teams setup:
  1. Register an Azure Bot (App ID + password)
  2. Set the messaging endpoint to POST /api/v1/integrations/teams/message
  3. Set TEAMS_APP_ID and TEAMS_APP_PASSWORD in your .env

Usage from Slack:
  /orchestrate Check disk on prod-server-01
  /orchestrate template disk-health-check host=prod-server-01 threshold_percent=90
  /run-status <run_id>

Usage from Teams:
  @OrchestratorBot Check disk on prod-server-01
  @OrchestratorBot template ssl-cert-check domain=api.example.com
"""

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


# ---------------------------------------------------------------------------
# Helpers: Slack signature verification
# ---------------------------------------------------------------------------


def _verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify the Slack request signature (HMAC-SHA256)."""
    secret = getattr(settings, "slack_signing_secret", "")
    if not secret:
        logger.warning("SLACK_SIGNING_SECRET not set; skipping signature verification")
        return True  # permissive when not configured (dev mode)

    # Reject stale requests (replay protection — 5-minute window)
    try:
        if abs(time.time() - float(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False

    base = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
    computed = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


# ---------------------------------------------------------------------------
# Helpers: post results back to Slack
# ---------------------------------------------------------------------------


async def _post_slack_message(response_url: str, text: str, is_error: bool = False) -> None:
    """POST a message back to a Slack response_url (delayed response)."""
    payload: Dict[str, Any] = {
        "response_type": "in_channel",
        "text": text,
    }
    if is_error:
        payload["response_type"] = "ephemeral"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(response_url, json=payload)
    except Exception as exc:
        logger.warning("Failed to post Slack delayed response: %s", exc)


async def _post_slack_api(channel: str, text: str, token: str) -> None:
    """Post a message via chat.postMessage (for @mention responses)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json={"channel": channel, "text": text},
            )
    except Exception as exc:
        logger.warning("Failed to post Slack API message: %s", exc)


# ---------------------------------------------------------------------------
# Helpers: parse commands and run orchestrator
# ---------------------------------------------------------------------------


def _parse_command(text: str) -> tuple[str, str, Dict[str, str]]:
    """Parse a bot command into (command_type, goal_or_template, params).

    Formats:
      <goal text>                                    → ("run", goal, {})
      template <name> key=val key=val               → ("template", name, {key: val})
      status <run_id>                               → ("status", run_id, {})
    """
    text = text.strip()
    if text.lower().startswith("template "):
        rest = text[9:].strip()
        parts = rest.split()
        if not parts:
            return ("run", text, {})
        template_name = parts[0]
        params: Dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                k, _, v = part.partition("=")
                params[k.strip()] = v.strip()
        return ("template", template_name, params)

    if text.lower().startswith("status "):
        run_id = text[7:].strip()
        return ("status", run_id, {})

    return ("run", text, {})


async def _execute_and_reply_slack(
    goal_or_template: str,
    command_type: str,
    params: Dict[str, str],
    response_url: str,
    bot_token: str = "",
    channel: str = "",
) -> None:
    """Run the orchestrator task and post the result back to Slack."""
    from app.core.run_store import create_run, get_run_by_id
    from app.core.run_templates import get_run_template, render_template_goal
    from app.llm.manager import LLMManager
    from app.planner.loop import run_planner_loop

    # Handle status query
    if command_type == "status":
        run = await get_run_by_id(goal_or_template)
        if run is None:
            await _post_slack_message(response_url, f"❌ Run `{goal_or_template}` not found.", is_error=True)
            return
        _emoji = {"completed": "✅", "failed": "❌", "running": "⏳", "cancelled": "🚫"}.get(run.status, "🔄")
        msg = f"{_emoji} *Run `{run.run_id[:8]}…`* — {run.status.upper()}\n"
        if run.answer:
            msg += f"\n{run.answer}"
        elif run.error:
            msg += f"\nError: {run.error}"
        await _post_slack_message(response_url, msg)
        return

    # Resolve goal
    if command_type == "template":
        template = get_run_template(goal_or_template)
        if template is None:
            await _post_slack_message(
                response_url,
                f"❌ Template `{goal_or_template}` not found. Try one of: disk-health-check, service-restart, ssl-cert-check, log-error-triage",
                is_error=True,
            )
            return
        try:
            goal, agent_profile_id = render_template_goal(template, params)
        except ValueError as exc:
            await _post_slack_message(response_url, f"❌ {exc}", is_error=True)
            return
    else:
        goal = goal_or_template
        agent_profile_id = "default"

    # Acknowledge immediately
    await _post_slack_message(
        response_url,
        f"⏳ Starting run for: _{goal[:120]}_\nI'll post results here when done.",
    )

    # Create and run
    run = await create_run(goal=goal, agent_profile_id=agent_profile_id, context={})
    llm_manager = LLMManager()

    try:
        await asyncio.wait_for(
            run_planner_loop(
                run_id=run.run_id,
                goal=goal,
                agent_profile_id=agent_profile_id,
                context={},
                llm_manager=llm_manager,
            ),
            timeout=300.0,  # 5-minute hard cap for bot interactions
        )
    except asyncio.TimeoutError:
        await _post_slack_message(
            response_url,
            f"⚠️ Run `{run.run_id[:8]}…` timed out after 5 minutes. Use `status {run.run_id}` to check.",
        )
        return

    finished = await get_run_by_id(run.run_id)
    if finished is None:
        await _post_slack_message(response_url, "❌ Run record not found after completion.")
        return

    if finished.status == "completed":
        msg = f"✅ *Done* — Run `{run.run_id[:8]}…`\n\n{finished.answer or '(no answer)'}"
    else:
        msg = f"❌ *Failed* — Run `{run.run_id[:8]}…`\n\nError: {finished.error or 'unknown'}"

    await _post_slack_message(response_url, msg)


# ---------------------------------------------------------------------------
# Slack endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/slack/command",
    summary="Slack slash command handler",
    description=(
        "Handles /orchestrate and /run-status Slack slash commands. "
        "Verifies request signature, dispatches to orchestrator, posts result to channel."
    ),
)
async def slack_command(request: Request, background_tasks: BackgroundTasks) -> Response:
    """Handle an inbound Slack slash command."""
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    # Parse x-www-form-urlencoded payload
    from urllib.parse import parse_qs

    parsed = parse_qs(body.decode("utf-8", errors="replace"))
    text = (parsed.get("text") or [""])[0].strip()
    response_url = (parsed.get("response_url") or [""])[0]
    command = (parsed.get("command") or ["/orchestrate"])[0]

    if command == "/run-status":
        text = f"status {text}"

    command_type, goal_or_template, params = _parse_command(text)

    bot_token = getattr(settings, "slack_bot_token", "")

    # Respond immediately with 200 (Slack requires < 3s), run in background
    background_tasks.add_task(
        _execute_and_reply_slack,
        goal_or_template=goal_or_template,
        command_type=command_type,
        params=params,
        response_url=response_url,
        bot_token=bot_token,
    )

    # Immediate acknowledgement
    return Response(
        content='{"response_type":"ephemeral","text":"⏳ Processing your request..."}',
        media_type="application/json",
    )


@router.post(
    "/slack/events",
    summary="Slack Events API handler",
    description="Handles Slack Events API payloads (app_mention, url_verification).",
)
async def slack_events(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Handle Slack Events API (app_mention for @orchestratorbot mentions)."""
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    import json

    payload = json.loads(body)

    # URL verification challenge (required by Slack during app setup)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event") or {}
    event_type = event.get("type")

    if event_type == "app_mention":
        # Strip the @mention from the text
        text: str = event.get("text", "")
        # Remove <@USERID> prefix
        import re

        text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
        channel = event.get("channel", "")
        bot_token = getattr(settings, "slack_bot_token", "")

        # Need a response_url equivalent — use chat.postMessage via bot token
        # Build a synthetic response_url as a closure over channel + token
        command_type, goal_or_template, params = _parse_command(text)

        async def _reply_via_api(message: str, is_error: bool = False) -> None:
            await _post_slack_api(channel, message, bot_token)

        # We pass an empty response_url and rely on bot_token + channel for replies
        background_tasks.add_task(
            _execute_and_reply_slack,
            goal_or_template=goal_or_template,
            command_type=command_type,
            params=params,
            response_url="",
            bot_token=bot_token,
            channel=channel,
        )

    return {"ok": True}


# ---------------------------------------------------------------------------
# Microsoft Teams endpoint
# ---------------------------------------------------------------------------


async def _verify_teams_token(authorization: str) -> bool:
    """Verify a Microsoft Teams Bot Framework JWT token (best-effort)."""
    # Full JWT validation requires fetching JWKS from Microsoft's OpenID config.
    # For production: use botframework-connector or jwt library with MS keys.
    # Here we check the token is present and non-empty (operators should use
    # network-level controls like Azure App Service Auth for stronger validation).
    app_id = getattr(settings, "teams_app_id", "")
    if not app_id:
        logger.warning("TEAMS_APP_ID not set; skipping Teams token verification")
        return True
    return bool(authorization and authorization.startswith("Bearer "))


@router.post(
    "/teams/message",
    summary="Microsoft Teams bot message handler",
    description=(
        "Handles inbound Microsoft Teams Bot Framework Activity payloads. "
        "Responds to messages directed at the bot."
    ),
)
async def teams_message(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Handle an inbound Teams message activity."""
    authorization = request.headers.get("Authorization", "")
    if not await _verify_teams_token(authorization):
        raise HTTPException(status_code=401, detail="Invalid Teams token")

    payload = await request.json()
    activity_type = payload.get("type")

    if activity_type != "message":
        return {"status": "ignored"}

    text: str = (payload.get("text") or "").strip()
    # Teams wraps HTML — strip basic tags
    import re

    text = re.sub(r"<[^>]+>", "", text).strip()

    # Reply-to details (needed to send response back)
    service_url: str = payload.get("serviceUrl", "")
    conversation_id: str = (payload.get("conversation") or {}).get("id", "")
    activity_id: str = payload.get("id", "")

    command_type, goal_or_template, params = _parse_command(text)

    background_tasks.add_task(
        _execute_and_reply_teams,
        goal_or_template=goal_or_template,
        command_type=command_type,
        params=params,
        service_url=service_url,
        conversation_id=conversation_id,
        activity_id=activity_id,
    )

    return {"status": "accepted"}


async def _execute_and_reply_teams(
    goal_or_template: str,
    command_type: str,
    params: Dict[str, str],
    service_url: str,
    conversation_id: str,
    activity_id: str,
) -> None:
    """Run the orchestrator task and post result back to Teams via Bot Framework."""
    from app.core.run_store import create_run, get_run_by_id
    from app.core.run_templates import get_run_template, render_template_goal
    from app.llm.manager import LLMManager
    from app.planner.loop import run_planner_loop

    app_id = getattr(settings, "teams_app_id", "")
    app_password = getattr(settings, "teams_app_password", "")

    async def _send(text: str) -> None:
        if not service_url or not conversation_id:
            return
        try:
            # Acquire Bot Framework token
            token = ""
            if app_id and app_password:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.post(
                        "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
                        data={
                            "grant_type": "client_credentials",
                            "client_id": app_id,
                            "client_secret": app_password,
                            "scope": "https://api.botframework.com/.default",
                        },
                    )
                    token = r.json().get("access_token", "")

            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"} if token else {"Content-Type": "application/json"}
            url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities/{activity_id}"
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(url, headers=headers, json={"type": "message", "text": text})
        except Exception as exc:
            logger.warning("Failed to send Teams reply: %s", exc)

    # Status query
    if command_type == "status":
        run = await get_run_by_id(goal_or_template)
        if run is None:
            await _send(f"Run `{goal_or_template}` not found.")
            return
        msg = f"Run `{run.run_id[:8]}…` — **{run.status.upper()}**"
        if run.answer:
            msg += f"\n\n{run.answer}"
        elif run.error:
            msg += f"\n\nError: {run.error}"
        await _send(msg)
        return

    # Resolve goal
    if command_type == "template":
        template = get_run_template(goal_or_template)
        if template is None:
            await _send(f"Template `{goal_or_template}` not found.")
            return
        try:
            goal, agent_profile_id = render_template_goal(template, params)
        except ValueError as exc:
            await _send(str(exc))
            return
    else:
        goal = goal_or_template
        agent_profile_id = "default"

    await _send(f"⏳ Starting run: _{goal[:120]}_")

    run = await create_run(goal=goal, agent_profile_id=agent_profile_id, context={})
    llm_manager = LLMManager()

    try:
        await asyncio.wait_for(
            run_planner_loop(
                run_id=run.run_id,
                goal=goal,
                agent_profile_id=agent_profile_id,
                context={},
                llm_manager=llm_manager,
            ),
            timeout=300.0,
        )
    except asyncio.TimeoutError:
        await _send(f"⚠️ Run `{run.run_id[:8]}…` timed out after 5 minutes.")
        return

    finished = await get_run_by_id(run.run_id)
    if finished and finished.status == "completed":
        await _send(f"✅ **Done** — Run `{run.run_id[:8]}…`\n\n{finished.answer or '(no answer)'}")
    else:
        error = (finished.error if finished else None) or "unknown"
        await _send(f"❌ **Failed** — Run `{run.run_id[:8]}…`\n\nError: {error}")
