"""Keep public prompt versions aligned with the instructions actually sent."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_voice_system_prompt_snapshot():
    tree = ast.parse((ROOT / "pi/bot.py").read_text(encoding="utf-8"))
    instructions = [
        ast.literal_eval(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "system_instruction"
    ]
    assert instructions == [(ROOT / "prompts/voice-system-v1.0.0.txt").read_text(encoding="utf-8")]


def test_telegram_system_prompt_snapshot():
    tree = ast.parse((ROOT / "pi/telegram_bridge.py").read_text(encoding="utf-8"))
    instructions = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SYSTEM" for target in node.targets)
    ]
    assert instructions == [(ROOT / "prompts/telegram-system-v1.0.0.txt").read_text(encoding="utf-8")]
