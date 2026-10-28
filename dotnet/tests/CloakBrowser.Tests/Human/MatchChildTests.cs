using System.Reflection;
using System.Text.Json;
using CloakBrowser.Human;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Human;

/// <summary>Mapping a Playwright frame to its CDP frame id (HumanWorld.MatchChild).</summary>
public class MatchChildTests
{
    public class FakeFrame : DispatchProxy
    {
        public string Name = "", Url = "";
        public List<IFrame> Kids = new();

        protected override object? Invoke(MethodInfo? m, object?[]? args) => m!.Name switch
        {
            "get_Name" => Name,
            "get_Url" => Url,
            "get_ChildFrames" => Kids,
            _ => throw new NotSupportedException(m.Name),
        };
    }

    private static IFrame F(string name, string url, params IFrame[] kids)
    {
        var f = DispatchProxy.Create<IFrame, FakeFrame>();
        var p = (FakeFrame)(object)f;
        p.Name = name; p.Url = url; p.Kids = kids.ToList();
        return f;
    }

    private static List<JsonElement> Kids(string json) =>
        JsonDocument.Parse(json).RootElement.EnumerateArray().ToList();

    [Fact]
    public void Survives_frame_renamed_by_page_js()
    {
        // CDP has the window.name set by page JS, Playwright the old one, and the
        // cross-site sibling (own process) is absent from the parent's CDP tree.
        var mid = F("m", "http://site.test/mid.html");
        var parent = F("", "", F("", "http://other.test/b.html"), mid);
        var kids = Kids("""[{"id":"MID","name":"renamed-by-js","url":"http://site.test/mid.html"}]""");
        Assert.Equal("MID", HumanWorld.MatchChild(mid, parent, kids));
    }

    [Fact]
    public void Same_url_siblings_keep_attach_order_after_rename()
    {
        var a = F("a", "http://site.test/w.html");
        var b = F("b", "http://site.test/w.html");
        var parent = F("", "", F("", "http://other.test/x.html"), a, b);
        var kids = Kids("""[{"id":"A","name":"a","url":"http://site.test/w.html"}, {"id":"B","name":"renamed","url":"http://site.test/w.html"}]""");
        Assert.Equal("A", HumanWorld.MatchChild(a, parent, kids));
        Assert.Equal("B", HumanWorld.MatchChild(b, parent, kids));
    }
}
