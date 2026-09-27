using System.Reflection;
using System.Runtime.Versioning;
using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol.Tests;

public sealed class PackageTests
{
    [Fact]
    public void The_package_targets_netstandard20_and_has_no_dependencies()
    {
        var assembly = typeof(JsonValue).Assembly;
        Assert.Equal(".NETStandard,Version=v2.0", assembly.GetCustomAttribute<TargetFrameworkAttribute>()?.FrameworkName);
        Assert.All(assembly.GetReferencedAssemblies(), a => Assert.Equal("netstandard", a.Name));
    }
}
