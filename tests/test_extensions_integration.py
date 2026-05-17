"""Integration test for extensions feature."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from cloakbrowser.browser import build_args


def test_extension_flags_in_build_args():
    """Test that extension flags are properly added to chrome args."""
    print("Testing extension flag integration...")
    
    # Mock extension paths
    ext_paths = [
        "/path/to/extensions/nkbihfbeogaeaoehlefnkodbefgpgknn",
        "/path/to/extensions/cjpalhdlnbpafiamejdnhcphjbkeiagm",
    ]
    
    paths_str = ",".join(ext_paths)
    extension_args = [
        f"--load-extension={paths_str}",
        f"--disable-extensions-except={paths_str}",
    ]
    
    # Build args with extension flags
    chrome_args = build_args(
        stealth_args=True,
        extra_args=extension_args,
        timezone=None,
        locale=None,
        headless=False,
    )
    
    # Verify extension flags are present
    load_ext_flag = [a for a in chrome_args if a.startswith("--load-extension=")]
    disable_ext_flag = [a for a in chrome_args if a.startswith("--disable-extensions-except=")]
    
    assert len(load_ext_flag) == 1, "Missing --load-extension flag"
    assert len(disable_ext_flag) == 1, "Missing --disable-extensions-except flag"
    
    # Verify paths are correctly formatted
    assert paths_str in load_ext_flag[0], f"Expected paths in {load_ext_flag[0]}"
    assert paths_str in disable_ext_flag[0], f"Expected paths in {disable_ext_flag[0]}"
    
    print("✓ Extension flags correctly integrated into build_args")
    print(f"  Load extension: {load_ext_flag[0]}")
    print(f"  Disable except: {disable_ext_flag[0]}")


def test_extension_parameter_accepted():
    """Test that launch_persistent_context accepts extensions parameter."""
    from cloakbrowser.browser import launch_persistent_context
    import inspect
    
    print("\nTesting extension parameter in function signature...")
    
    sig = inspect.signature(launch_persistent_context)
    params = sig.parameters
    
    assert "extensions" in params, "extensions parameter not found in launch_persistent_context"
    
    # Check default value
    ext_param = params["extensions"]
    assert ext_param.default is None, f"Expected default None, got {ext_param.default}"
    assert "list[str]" in str(ext_param.annotation), f"Expected list[str] type hint, got {ext_param.annotation}"
    
    print("✓ extensions parameter correctly defined")
    print(f"  Type: {ext_param.annotation}")
    print(f"  Default: {ext_param.default}")


def test_async_extension_parameter():
    """Test that launch_persistent_context_async accepts extensions parameter."""
    from cloakbrowser.browser import launch_persistent_context_async
    import inspect
    
    print("\nTesting extension parameter in async function signature...")
    
    sig = inspect.signature(launch_persistent_context_async)
    params = sig.parameters
    
    assert "extensions" in params, "extensions parameter not found in launch_persistent_context_async"
    
    ext_param = params["extensions"]
    assert ext_param.default is None, f"Expected default None, got {ext_param.default}"
    assert "list[str]" in str(ext_param.annotation), f"Expected list[str] type hint, got {ext_param.annotation}"
    
    print("✓ extensions parameter correctly defined in async function")
    print(f"  Type: {ext_param.annotation}")
    print(f"  Default: {ext_param.default}")


if __name__ == "__main__":
    print("=== Extension Integration Tests ===\n")
    
    test_extension_flags_in_build_args()
    test_extension_parameter_accepted()
    test_async_extension_parameter()
    
    print("\n=== All integration tests passed ===")
