"""Copy skills/xlens/SKILL.md into each plugin. Run after editing the skill."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skills/xlens/SKILL.md"
for plugin in ("claude", "codex"):
    dst = ROOT / "plugins" / plugin / "skills/xlens/SKILL.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC, dst)
    print(dst.relative_to(ROOT))
