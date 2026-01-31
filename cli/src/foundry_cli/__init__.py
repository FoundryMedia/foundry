# Compatibility shim for paramiko 3.0+ (DSSKey was removed as DSA is deprecated)
# sshtunnel 0.4.0 still references paramiko.DSSKey, so we need to patch it
# This must run before any sshtunnel import
def _patch_paramiko_for_sshtunnel():
    """Add a stub DSSKey to paramiko if missing (removed in paramiko 3.0+)."""
    try:
        import paramiko
        if not hasattr(paramiko, 'DSSKey'):
            # Create a dummy class that will never match any key type
            # This allows sshtunnel to load without crashing
            class _DSSKeyStub:
                """Stub for removed paramiko.DSSKey (DSA keys are deprecated)."""
                pass
            paramiko.DSSKey = _DSSKeyStub
    except ImportError:
        pass

_patch_paramiko_for_sshtunnel()


from foundry_cli.release.versioning import VersionResolutionError, get_local_version

__all__ = ["get_local_version", "VersionResolutionError"]