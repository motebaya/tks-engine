from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.logger_manager import LoggerManager


@dataclass
class VideoFile:
  """
  Metadata for a scanned video file.

  :param path: Full path to the video file.
  :type path: Path
  :param filename: File name without directory.
  :type filename: str
  :param size_bytes: File size in bytes.
  :type size_bytes: int
  :param size_human: Human-readable size string.
  :type size_human: str
  """

  path: Path
  filename: str
  size_bytes: int
  size_human: str


class FileScanner:
  """
  Scans a target directory for uploadable .mp4 video files, collects
  metadata, detects duplicates, and filters against already-scheduled files.

  :param logger: Logger instance for status messages.
  :type logger: LoggerManager
  """

  SUPPORTED_EXTENSIONS: list[str] = [".mp4"]

  def __init__(self, logger: LoggerManager) -> None:
    """
    Initialize FileScanner.

    :param logger: Logger instance.
    :type logger: LoggerManager
    """
    self._logger = logger

  def scan(self, directory: Path) -> list[VideoFile]:
    """
    Recursively scan a directory for .mp4 video files.

    :param directory: Root directory to scan.
    :type directory: Path
    :return: List of VideoFile records sorted by filename.
    :rtype: list[VideoFile]
    :raises FileNotFoundError: If the directory does not exist.
    :raises NotADirectoryError: If the path is not a directory.
    """
    if not directory.exists():
      raise FileNotFoundError(f"Directory not found: {directory}")
    if not directory.is_dir():
      raise NotADirectoryError(f"Path is not a directory: {directory}")

    self._logger.info(f"Scanning directory: {directory}")
    files: list[VideoFile] = []

    for file_path in directory.rglob("*"):
      if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
        size = file_path.stat().st_size
        if size > 0:
          video = VideoFile(
            path=file_path,
            filename=file_path.name,
            size_bytes=size,
            size_human=self._format_size(size),
          )
          files.append(video)

    files.sort(key=lambda v: v.filename.lower())
    self._logger.info(f"Found {len(files)} video file(s)")
    return files

  def filter_scheduled(
    self,
    files: list[VideoFile],
    scheduled: list[dict],
  ) -> list[VideoFile]:
    """
    Remove files that already appear in the scheduled upload records.

    Matching is done by basename comparison (the 'file' key in
    the per-user schedule file stores the basename).

    :param files: List of scanned video files.
    :type files: list[VideoFile]
    :param scheduled: List of upload record dicts (each with a 'file' key).
    :type scheduled: list[dict]
    :return: Files not yet scheduled.
    :rtype: list[VideoFile]
    """
    scheduled_names = self.get_scheduled_basenames(scheduled)

    filtered = [
      f for f in files
      if f.filename not in scheduled_names
    ]

    removed_count = len(files) - len(filtered)
    if removed_count > 0:
      self._logger.info(f"Filtered out {removed_count} already-scheduled file(s)")

    return filtered

  @staticmethod
  def get_scheduled_basenames(scheduled: list[dict]) -> set[str]:
    """
    Extract the set of basenames from scheduled upload records.

    :param scheduled: List of upload record dicts.
    :type scheduled: list[dict]
    :return: Set of basenames that have status 'success'.
    :rtype: set[str]
    """
    names: set[str] = set()
    for record in scheduled:
      file_val = record.get("file", "")
      status = record.get("status", "")
      if file_val and status == "success":
        # file_val may be basename or full path — extract name part
        names.add(Path(file_val).name)
    return names

  def detect_duplicates(self, files: list[VideoFile]) -> list[list[VideoFile]]:
    """
    Group files with identical filenames (potential duplicates).

    Files are grouped by lowercase filename. Only groups with more than
    one file are returned.

    :param files: List of video files to check.
    :type files: list[VideoFile]
    :return: List of groups, where each group contains 2+ files sharing a name.
    :rtype: list[list[VideoFile]]
    """
    groups: dict[str, list[VideoFile]] = {}
    for f in files:
      key = f.filename.lower()
      if key not in groups:
        groups[key] = []
      groups[key].append(f)

    duplicates = [g for g in groups.values() if len(g) > 1]

    if duplicates:
      total = sum(len(g) for g in duplicates)
      self._logger.warning(
        f"Detected {len(duplicates)} duplicate group(s) ({total} files)"
      )

    return duplicates

  @staticmethod
  def _format_size(size_bytes: int) -> str:
    """
    Convert bytes to a human-readable size string.

    :param size_bytes: Size in bytes.
    :type size_bytes: int
    :return: Formatted string like '12.3 MB'.
    :rtype: str
    """
    if size_bytes < 1024:
      return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
      return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
      return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
      return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
