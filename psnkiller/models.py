"""Estructuras de datos compartidas."""
from dataclasses import dataclass


@dataclass
class ContentItem:
    category: str
    title_id: str
    region: str
    name: str
    version: str
    size: str
    url: str
    content_id: str = ""
    match_type: str = ""
    platform: str = "PS3"
    license_value: str = ""
    sha256: str = ""
    required_fw: str = ""
    original_name: str = ""
    item_type: str = ""


@dataclass
class DownloadTask:
    task_id: int
    url: str
    dest_path: str
    title: str
    platform: str
    category: str
    base_item: ContentItem = None
    manifest_item: ContentItem = None
    game_key: str = ""
    status: str = "queued"
    progress: float = 0.0
    speed: str = ""
    error: str = ""
    created_at: str = ""
    completed_at: str = ""
    total_size: int = 0
    resume_path: str = ""


class DownloadCancelled(Exception):
    """El usuario canceló la tarea mientras se descargaba."""
