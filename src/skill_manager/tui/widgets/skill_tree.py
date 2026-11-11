"""SkillTree widget for hierarchical and badged skill navigation (FR-10)."""

from __future__ import annotations

from typing import List, Optional

from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from skill_manager.models import SkillEntity, SkillExecutionMode


class SkillTree(Tree[SkillEntity]):
    """Tree widget presenting local skills grouped by platform with mode and health badges."""

    COMPONENT_CLASSES = {"skill-tree--badge"}

    class SkillSelected(Message):
        """Emitted when a skill node is highlighted or activated."""

        def __init__(self, skill: SkillEntity) -> None:
            super().__init__()
            self.skill = skill

    def __init__(
        self,
        label: str = "Local Skills",
        skills: Optional[List[SkillEntity]] = None,
        id: Optional[str] = None,
    ) -> None:
        super().__init__(label, id=id)
        self.root.expand()
        self._skills: List[SkillEntity] = skills or []
        if self._skills:
            self.populate(self._skills)

    def populate(self, skills: List[SkillEntity], filter_query: str = "") -> None:
        """Populate tree nodes categorized by platform."""
        self.root.remove_children()
        self.root.expand()
        self._skills = skills
        query_norm = filter_query.strip().lower()

        # Group by platform
        by_platform: dict[str, list[SkillEntity]] = {}
        for s in skills:
            if query_norm and (query_norm not in s.name.lower() and query_norm not in s.id.lower()):
                continue
            plat = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            by_platform.setdefault(plat, []).append(s)

        for plat_name, plat_skills in sorted(by_platform.items()):
            plat_node = self.root.add(f"[bold]{plat_name.capitalize()}[/bold] ({len(plat_skills)})", expand=True)
            for skill in sorted(plat_skills, key=lambda x: x.name):
                mode_icon = "📌" if skill.execution_mode == SkillExecutionMode.RESIDENT else "⚡"
                health_icon = "🟢" if skill.has_skill_md else "🔴"
                node_label = f"{health_icon} {mode_icon} {skill.name}"
                plat_node.add_leaf(node_label, data=skill)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Post message when user navigates tree."""
        if event.node and event.node.data and isinstance(event.node.data, SkillEntity):
            self.post_message(self.SkillSelected(event.node.data))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Post message on Enter/Click."""
        if event.node and event.node.data and isinstance(event.node.data, SkillEntity):
            self.post_message(self.SkillSelected(event.node.data))
