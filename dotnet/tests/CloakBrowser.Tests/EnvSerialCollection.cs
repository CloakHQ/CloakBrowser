using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Serializes test classes that mutate process environment variables
/// (CLOAKBROWSER_DOWNLOAD_URL, CLOAKBROWSER_LICENSE_KEY, CLOAKBROWSER_CACHE_DIR, ...)
/// so they don't race under xUnit's default cross-collection parallelism.
/// </summary>
[CollectionDefinition("env-serial")]
public sealed class EnvSerialCollection { }
