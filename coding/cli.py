import asyncio
import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from coding.agent import LasmeCodingAgent
from core.config import settings

app = typer.Typer(help="LasmeLLMCoding - Autonomous Local Coding Agent")
console = Console(force_terminal=True, soft_wrap=True)

def agent_callback(event_type: str, payload: str, meta: dict = None):
    # coding/agent.py appelle callback(type, payload, meta) : le callback de
    # la CLI accepte les trois arguments (le 3e porte le contexte d'étape).
    try:
        if event_type == "status":
            console.print(f"[bold blue][INFO] {payload}[/bold blue]")
        elif event_type == "thought":
            console.print(Panel(Markdown(payload), title="[bold green]Thought[/bold green]", border_style="green"))
        elif event_type == "tool_call":
            console.print(f"[bold yellow][TOOL] {payload}[/bold yellow]")
        elif event_type == "tool_result":
            console.print(Panel(payload, title="[dim]Tool Result[/dim]", border_style="dim"))
    except Exception:
        print(f"[{event_type}] {payload}")


@app.command()
def run(
    prompt: str = typer.Argument(..., help="Task prompt for the coding agent"),
    model: str = typer.Option(settings.coding_model, "--model", "-m", help="Model profile to use (llama.cpp router)")
):
    """Run LasmeLLMCoding agent on a task prompt."""
    console.print(Panel(f"[bold magenta]LasmeLLMCoding Agent[/bold magenta]\nModel: [cyan]{model}[/cyan]\nTask: {prompt}", border_style="magenta"))
    
    agent = LasmeCodingAgent(model_name=model)
    
    async def _start():
        result = await agent.execute_task(prompt, callback=agent_callback)
        console.print(Panel(Markdown(result), title="[bold cyan]Final Response[/bold cyan]", border_style="cyan"))

    asyncio.run(_start())

if __name__ == "__main__":
    app()
