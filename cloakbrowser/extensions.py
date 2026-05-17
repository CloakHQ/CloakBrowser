"""Chrome extension download and injection utilities for CloakBrowser.

Provides download_and_extract_extension() to fetch extensions from the Chrome Web Store
and extract them for use with Chromium's --load-extension flag.

Supports automatic extension installation when launching persistent contexts.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger("cloakbrowser")

# Chrome Web Store download URL template
CWS_DOWNLOAD_URL = "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=146.0&acceptformat=crx2,crx3&x=id%3D{extension_id}%26uc"

# User-Agent to spoof as a real Chrome browser
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"


def download_and_extract_extension(extension_id: str, profile_dir: str | os.PathLike) -> str:
    """Download and extract a Chrome extension from the Chrome Web Store.

    Downloads the extension as a .crx/.zip file from the official Chrome Web Store
    using a spoofed User-Agent, then extracts it into a dedicated folder within
    the profile's extensions directory.

    Args:
        extension_id: Chrome Web Store extension ID (e.g., 'nkbihfbeogaeaoehlefnkodbefgpgknn' for MetaMask).
        profile_dir: Path to the browser profile directory (user_data_dir).

    Returns:
        Absolute path to the extracted extension folder (e.g., /path/to/profile/extensions/{extension_id}).

    Raises:
        ValueError: If extension_id is empty or invalid format.
        RuntimeError: If download fails, extraction fails, or file system operations fail.
        OSError: If unable to create directories or write files.

    Example:
        >>> ext_path = download_and_extract_extension('nkbihfbeogaeaoehlefnkodbefgpgknn', './my-profile')
        >>> print(f"Extension installed at: {ext_path}")
        Extension installed at: /abs/path/to/my-profile/extensions/nkbihfbeogaeaoehlefnkodbefgpgknn
    """
    # Validate extension ID
    extension_id = extension_id.strip()
    if not extension_id:
        raise ValueError("extension_id cannot be empty")
    if not _is_valid_extension_id(extension_id):
        raise ValueError(f"Invalid extension ID format: {extension_id}")

    profile_dir_path = Path(profile_dir)
    extensions_dir = profile_dir_path / "extensions"
    ext_extract_dir = extensions_dir / extension_id

    logger.info(f"Downloading extension: {extension_id}")

    try:
        # Create extensions directory if it doesn't exist
        extensions_dir.mkdir(parents=True, exist_ok=True)

        # If extension already exists, skip download and return path
        if ext_extract_dir.exists() and list(ext_extract_dir.iterdir()):
            logger.info(f"Extension {extension_id} already exists at {ext_extract_dir}")
            return str(ext_extract_dir.resolve())

        # Download the extension
        crx_data = _download_extension(extension_id)
        logger.debug(f"Downloaded {len(crx_data)} bytes for extension {extension_id}")

        # Extract to temporary directory first
        temp_dir = tempfile.mkdtemp(prefix=f"cloakbrowser_ext_{extension_id}_")
        temp_path = Path(temp_dir)

        try:
            _extract_crx(crx_data, temp_path)
            logger.debug(f"Extracted extension to temporary directory: {temp_dir}")

            # Clean up old extraction if it exists
            if ext_extract_dir.exists():
                shutil.rmtree(ext_extract_dir)
                logger.debug(f"Cleaned up old extension directory: {ext_extract_dir}")

            # Move extracted files to final location
            shutil.move(str(temp_path), str(ext_extract_dir))
            logger.info(f"Extension {extension_id} installed successfully to {ext_extract_dir}")

            return str(ext_extract_dir.resolve())

        finally:
            # Clean up temporary directory
            if Path(temp_dir).exists():
                try:
                    shutil.rmtree(temp_dir)
                except OSError as e:
                    logger.warning(f"Failed to clean up temporary directory {temp_dir}: {e}")

    except Exception as e:
        logger.error(f"Failed to download/extract extension {extension_id}: {e}", exc_info=True)
        raise RuntimeError(f"Failed to process extension {extension_id}: {e}") from e


def _is_valid_extension_id(extension_id: str) -> bool:
    """Validate Chrome extension ID format.

    Extension IDs are 32 lowercase hexadecimal characters.
    """
    return len(extension_id) == 32 and all(c in "abcdefghijklmnopqrstuvwxyz0123456789" for c in extension_id)


def _download_extension(extension_id: str) -> bytes:
    """Download extension .crx file from Chrome Web Store.

    Args:
        extension_id: Chrome extension ID.

    Returns:
        Raw bytes of the downloaded .crx file.

    Raises:
        RuntimeError: If download fails.
    """
    url = CWS_DOWNLOAD_URL.format(extension_id=extension_id)

    try:
        logger.debug(f"Downloading from: {url}")

        # Create request with spoofed User-Agent
        req = Request(url, headers={"User-Agent": USER_AGENT})

        # Download with timeout
        with urlopen(req, timeout=30) as response:
            data = response.read()

        if not data:
            raise RuntimeError("Downloaded empty file")

        logger.debug(f"Download successful: {len(data)} bytes")
        return data

    except Exception as e:
        logger.error(f"Download failed for extension {extension_id}: {e}")
        raise RuntimeError(f"Failed to download extension from Chrome Web Store: {e}") from e


def _extract_crx(crx_data: bytes, extract_to: Path) -> None:
    """Extract .crx/.zip file contents.

    .crx files are ZIP archives with a 4-byte header (magic number) that must be skipped.
    The magic number is 'Cr24' (0x4372 0x3234 in big-endian, or 43 72 32 34 in hex).

    Args:
        crx_data: Raw bytes of the .crx/.zip file.
        extract_to: Directory path to extract files to.

    Raises:
        RuntimeError: If extraction fails or file is corrupted.
    """
    try:
        extract_to.mkdir(parents=True, exist_ok=True)

        # Try as-is first (might be a pure ZIP without CRX header)
        try:
            with zipfile.ZipFile(io.BytesIO(crx_data), "r") as zf:
                logger.debug("Extracting as raw ZIP file")
                zf.extractall(extract_to)
                return
        except zipfile.BadZipFile:
            logger.debug("Not a raw ZIP, attempting CRX format with header skip")

        # CRX format: skip the first 4-16 bytes (magic + version/metadata)
        # Standard CRX3: 4 bytes magic ('Cr24') + 4 bytes version + 8 bytes length
        # Try skipping different offsets
        for skip_bytes in [16, 12, 4]:
            try:
                with zipfile.ZipFile(io.BytesIO(crx_data[skip_bytes:]), "r") as zf:
                    logger.debug(f"Extracting with {skip_bytes}-byte header skip")
                    zf.extractall(extract_to)
                    return
            except (zipfile.BadZipFile, Exception):
                continue

        raise RuntimeError("Could not extract CRX: invalid format or corrupted archive")

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to extract extension archive: {e}") from e


def get_extension_paths(extension_ids: list[str], profile_dir: str | os.PathLike) -> list[str]:
    """Get absolute paths for a list of extension IDs in a profile.

    Does not download extensions - assumes they are already present.
    Filters out non-existent extensions with a warning.

    Args:
        extension_ids: List of extension IDs to get paths for.
        profile_dir: Path to the profile directory.

    Returns:
        List of absolute paths to existing extension directories.
    """
    profile_dir_path = Path(profile_dir)
    paths = []

    for ext_id in extension_ids:
        ext_path = profile_dir_path / "extensions" / ext_id
        if ext_path.exists():
            paths.append(str(ext_path.resolve()))
        else:
            logger.warning(f"Extension {ext_id} not found at {ext_path}")

    return paths
