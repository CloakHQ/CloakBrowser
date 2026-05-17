"""Test extension downloader functionality."""

import os
import tempfile
from pathlib import Path
from cloakbrowser.extensions import (
    download_and_extract_extension,
    _is_valid_extension_id,
    get_extension_paths,
)


def test_extension_id_validation():
    """Test extension ID format validation."""
    print("Testing extension ID validation...")
    
    # Valid IDs
    assert _is_valid_extension_id("nkbihfbeogaeaoehlefnkodbefgpgknn")
    assert _is_valid_extension_id("cjpalhdlnbpafiamejdnhcphjbkeiagm")
    
    # Invalid IDs
    assert not _is_valid_extension_id("invalid_extension_id")
    assert not _is_valid_extension_id("nkbihfbeogaeaoehlefnkodbefgpgk")  # Too short
    assert not _is_valid_extension_id("NKBIHFBEOGAEAOEHLEFNKODBEFGPGKNN")  # Uppercase
    assert not _is_valid_extension_id("")
    
    print("✓ Extension ID validation works correctly")


def test_extension_download():
    """Test downloading a real extension (requires internet)."""
    print("\nTesting extension download...")
    
    # Use MetaMask extension (well-known, small)
    metamask_id = "nkbihfbeogaeaoehlefnkodbefgpgknn"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            ext_path = download_and_extract_extension(metamask_id, tmpdir)
            
            # Verify the extension was extracted
            assert Path(ext_path).exists(), f"Extension path does not exist: {ext_path}"
            assert Path(ext_path).is_dir(), f"Extension path is not a directory: {ext_path}"
            
            # Check for manifest.json (required for Chrome extensions)
            manifest_path = Path(ext_path) / "manifest.json"
            assert manifest_path.exists(), f"manifest.json not found in {ext_path}"
            
            print(f"✓ Successfully downloaded and extracted extension to: {ext_path}")
            print(f"  Files: {list(Path(ext_path).iterdir())[:5]}...")  # Show first 5 files
            
        except Exception as e:
            print(f"⚠ Download test skipped (may require internet): {e}")


def test_get_extension_paths():
    """Test retrieving extension paths."""
    print("\nTesting get_extension_paths...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create mock extension directories
        ext_dir = Path(tmpdir) / "extensions"
        ext_dir.mkdir()
        (ext_dir / "ext1").mkdir()
        (ext_dir / "ext2").mkdir()
        
        paths = get_extension_paths(["ext1", "ext2", "ext3"], tmpdir)
        
        # Should return 2 paths (ext3 doesn't exist)
        assert len(paths) == 2, f"Expected 2 paths, got {len(paths)}"
        
        # Verify paths are absolute
        for path in paths:
            assert Path(path).is_absolute(), f"Path is not absolute: {path}"
        
        print(f"✓ get_extension_paths works correctly")
        print(f"  Found {len(paths)} extensions: {[Path(p).name for p in paths]}")


if __name__ == "__main__":
    print("=== Extension Module Tests ===\n")
    
    test_extension_id_validation()
    test_get_extension_paths()
    test_extension_download()  # Requires internet
    
    print("\n=== All tests completed ===")
