using CloakBrowser;
using CloakBrowser.Human;
using Xunit;
using Range = CloakBrowser.Human.Range;

namespace CloakBrowser.Tests;

public class GeoIpTests
{
    [Theory]
    [InlineData("10.0.0.1", true)]
    [InlineData("192.168.1.1", true)]
    [InlineData("172.16.0.1", true)]
    [InlineData("127.0.0.1", true)]
    [InlineData("8.8.8.8", false)]
    [InlineData("1.1.1.1", false)]
    public void IsPrivateIp_Classifies(string ip, bool isPrivate)
    {
        Assert.Equal(isPrivate, GeoIp.IsPrivateIp(ip));
    }

    [Fact]
    public void CountryLocaleMap_HasCommonCountries()
    {
        Assert.True(GeoIp.CountryLocaleMap.ContainsKey("US"));
        Assert.True(GeoIp.CountryLocaleMap.ContainsKey("DE"));
    }
}

public class HumanRandomTests
{
    [Fact]
    public void Rand_InRange()
    {
        for (int i = 0; i < 1000; i++)
        {
            double v = HumanRandom.Rand(5, 10);
            Assert.InRange(v, 5, 10);
        }
    }

    [Fact]
    public void RandInt_Inclusive()
    {
        var seen = new HashSet<int>();
        for (int i = 0; i < 1000; i++)
            seen.Add(HumanRandom.RandInt(1, 3));
        Assert.Equal(new HashSet<int> { 1, 2, 3 }, seen);
    }

    [Fact]
    public void RandRange_FromRange()
    {
        var r = new Range(2, 4);
        for (int i = 0; i < 500; i++)
            Assert.InRange(HumanRandom.RandRange(r), 2, 4);
    }

    [Fact]
    public void Choice_FromString()
    {
        var seen = new HashSet<char>();
        for (int i = 0; i < 500; i++)
            seen.Add(HumanRandom.Choice("abc"));
        Assert.Equal(new HashSet<char> { 'a', 'b', 'c' }, seen);
    }

    [Fact]
    public void SleepMs_Zero_IsNoOp()
    {
        // Should not throw and should return quickly.
        HumanRandom.SleepMs(0);
        Assert.True(HumanRandom.SleepMsAsync(0).IsCompleted);
    }
}

public class KeyboardTests
{
    [Fact]
    public void ShiftSymbols_Contains_Expected()
    {
        foreach (char c in "@#!$%^&*()_+{}|:\"<>?~")
            Assert.Contains(c, HumanKeyboard.ShiftSymbols);
    }

    [Fact]
    public void NearbyKeys_HasQwertyNeighbors()
    {
        Assert.Equal("sqwz", HumanKeyboard.NearbyKeys['a']);
        Assert.Equal("ol", HumanKeyboard.NearbyKeys['p']);
    }
}

public class ActionabilityTests
{
    [Fact]
    public void CheckSets_Match_Python()
    {
        Assert.Equal(new HashSet<string> { "attached", "visible", "enabled", "pointer_events" },
            new HashSet<string>(Actionability.ChecksClick));
        Assert.Equal(new HashSet<string> { "attached", "visible", "pointer_events" },
            new HashSet<string>(Actionability.ChecksHover));
        Assert.Equal(new HashSet<string> { "attached", "visible", "enabled", "editable", "pointer_events" },
            new HashSet<string>(Actionability.ChecksInput));
        Assert.Equal(new HashSet<string> { "attached", "visible", "enabled" },
            new HashSet<string>(Actionability.ChecksFocus));
    }

    [Fact]
    public void ErrorHierarchy_AllSubclassActionabilityError()
    {
        Assert.IsAssignableFrom<ActionabilityError>(new ElementNotAttachedError("#x"));
        Assert.IsAssignableFrom<ActionabilityError>(new ElementNotVisibleError("#x"));
        Assert.IsAssignableFrom<ActionabilityError>(new ElementNotStableError("#x"));
        Assert.IsAssignableFrom<ActionabilityError>(new ElementNotEnabledError("#x"));
        Assert.IsAssignableFrom<ActionabilityError>(new ElementNotEditableError("#x"));
        Assert.IsAssignableFrom<ActionabilityError>(new ElementNotReceivingEventsError("#x", "div"));
    }

    [Fact]
    public void ElementNotReceivingEvents_Message_IncludesCoveringTag()
    {
        var e = new ElementNotReceivingEventsError("#x", "span");
        Assert.Contains("span", e.Message);
        Assert.Equal("pointer_events", e.Check);
    }
}

public class MouseMathTests
{
    [Fact]
    public void ClickTarget_Input_Within_Box()
    {
        var box = new BoundingBox(100, 200, 300, 40);
        var cfg = new HumanConfig();
        for (int i = 0; i < 200; i++)
        {
            var p = HumanMouse.ClickTarget(box, isInput: true, cfg);
            Assert.InRange(p.X, box.X, box.X + box.Width);
            Assert.InRange(p.Y, box.Y, box.Y + box.Height);
        }
    }

    [Fact]
    public void ClickTarget_Button_Clusters_Center()
    {
        var box = new BoundingBox(0, 0, 100, 100);
        var cfg = new HumanConfig();
        for (int i = 0; i < 200; i++)
        {
            var p = HumanMouse.ClickTarget(box, isInput: false, cfg);
            Assert.InRange(p.X, 35, 65);
            Assert.InRange(p.Y, 35, 65);
        }
    }
}
