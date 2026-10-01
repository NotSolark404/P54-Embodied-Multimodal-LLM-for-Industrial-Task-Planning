"""
vision_backend/
---------------
Vision module for the Multimodal LLM Industrial Task Planning system.
Sprint 1 — PB3 / PB4 / PB5

Public interface:
    from vision_backend.scene_representation import get_current_scene, get_planner_scene
    from vision_backend.spatial_relationships import compute_relationships
    from vision_backend.vision_output         import create_detection, create_scene_output
"""

try:
    from vision_backend.scene_representation import (
        get_current_scene,
        get_planner_scene,
        build_scene_representation,
        calculate_center,
    )
except ImportError:
    pass

try:
    from vision_backend.spatial_relationships import (
        compute_relationships,
        get_spatial_relationships,
        build_spatial_output,
    )
except ImportError:
    pass

try:
    from vision_backend.vision_output import (
        create_detection,
        create_scene_output,
    )
except ImportError:
    pass

__all__ = [
    "get_current_scene",
    "get_planner_scene",
    "build_scene_representation",
    "calculate_center",
    "compute_relationships",
    "get_spatial_relationships",
    "build_spatial_output",
    "create_detection",
    "create_scene_output",
]
