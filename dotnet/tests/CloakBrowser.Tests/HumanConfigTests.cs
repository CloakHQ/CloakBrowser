using CloakBrowser.Human;
using Xunit;

namespace CloakBrowser.Tests;

public class HumanConfigTests
{
    [Fact]
    public void DefaultPreset_HasExpectedDefaults()
    {
        var cfg = HumanConfigFactory.Resolve(HumanPreset.Default);
        Assert.Equal(70, cfg.TypingDelay);
        Assert.Equal((15, 35), (cfg.KeyHold.Min, cfg.KeyHold.Max));
        Assert.False(cfg.IdleBetweenActions);
    }

    [Fact]
    public void CarefulPreset_IsSlower()
    {
        var cfg = HumanConfigFactory.Resolve(HumanPreset.Careful);
        Assert.Equal(100, cfg.TypingDelay);
        Assert.True(cfg.IdleBetweenActions);
        Assert.Equal((20, 45), (cfg.KeyHold.Min, cfg.KeyHold.Max));
    }

    [Fact]
    public void Overrides_SnakeCase_Keys_Applied()
    {
        var cfg = HumanConfigFactory.Resolve(HumanPreset.Default, new Dictionary<string, object>
        {
            ["typing_delay"] = 200.0,
            ["mistype_chance"] = 0.5,
        });
        Assert.Equal(200, cfg.TypingDelay);
        Assert.Equal(0.5, cfg.MistypeChance);
    }

    [Fact]
    public void Overrides_PascalCase_Keys_Applied()
    {
        var cfg = HumanConfigFactory.Resolve(HumanPreset.Default, new Dictionary<string, object>
        {
            ["TypingDelay"] = 250.0,
        });
        Assert.Equal(250, cfg.TypingDelay);
    }

    [Fact]
    public void Overrides_Range_From_Tuple()
    {
        var cfg = HumanConfigFactory.Resolve(HumanPreset.Default, new Dictionary<string, object>
        {
            ["key_hold"] = (50.0, 100.0),
        });
        Assert.Equal((50, 100), (cfg.KeyHold.Min, cfg.KeyHold.Max));
    }

    [Fact]
    public void Overrides_Range_From_Array()
    {
        var cfg = HumanConfigFactory.Resolve(HumanPreset.Default, new Dictionary<string, object>
        {
            ["key_hold"] = new object[] { 60, 120 },
        });
        Assert.Equal((60, 120), (cfg.KeyHold.Min, cfg.KeyHold.Max));
    }

    [Fact]
    public void Unknown_Keys_Ignored()
    {
        var cfg = HumanConfigFactory.Resolve(HumanPreset.Default, new Dictionary<string, object>
        {
            ["does_not_exist"] = 5,
        });
        Assert.Equal(70, cfg.TypingDelay); // unchanged
    }

    [Fact]
    public void ParsePreset_CaseInsensitive()
    {
        Assert.Equal(HumanPreset.Careful, HumanConfigFactory.ParsePreset("CAREFUL"));
        Assert.Equal(HumanPreset.Default, HumanConfigFactory.ParsePreset(null));
    }

    [Fact]
    public void ParsePreset_Invalid_Throws()
    {
        Assert.Throws<System.ArgumentException>(() => HumanConfigFactory.ParsePreset("nope"));
    }

    [Fact]
    public void With_DoesNotMutate_Base()
    {
        var baseCfg = new HumanConfig();
        var merged = baseCfg.With(new Dictionary<string, object> { ["typing_delay"] = 999.0 });
        Assert.Equal(70, baseCfg.TypingDelay);
        Assert.Equal(999, merged.TypingDelay);
    }

    [Fact]
    public void With_ReturnsNewInstance_NotSameReference()
    {
        var baseCfg = new HumanConfig();
        var merged = baseCfg.With(new Dictionary<string, object> { ["typing_delay"] = 123.0 });
        Assert.NotSame(baseCfg, merged);
    }

    [Fact]
    public void With_NullOverrides_ReturnsEquivalentClone()
    {
        var baseCfg = new HumanConfig { TypingDelay = 42, MistypeChance = 0.3 };
        var merged = baseCfg.With(null);

        // Equivalent values but a distinct instance (never the same reference).
        Assert.NotSame(baseCfg, merged);
        Assert.Equal(42, merged.TypingDelay);
        Assert.Equal(0.3, merged.MistypeChance);
    }

    [Fact]
    public void With_EmptyOverrides_ReturnsEquivalentClone()
    {
        var baseCfg = new HumanConfig { TypingDelay = 55 };
        var merged = baseCfg.With(new Dictionary<string, object>());

        Assert.NotSame(baseCfg, merged);
        Assert.Equal(55, merged.TypingDelay);
    }

    [Fact]
    public void With_PreservesNonOverriddenFields()
    {
        var baseCfg = new HumanConfig(); // defaults
        var merged = baseCfg.With(new Dictionary<string, object> { ["typing_delay"] = 500.0 });

        // The overridden field changed...
        Assert.Equal(500, merged.TypingDelay);
        // ...while every non-overridden field keeps its base value.
        Assert.Equal(baseCfg.MistypeChance, merged.MistypeChance);
        Assert.Equal((baseCfg.KeyHold.Min, baseCfg.KeyHold.Max), (merged.KeyHold.Min, merged.KeyHold.Max));
        Assert.Equal(baseCfg.MouseMinSteps, merged.MouseMinSteps);
        Assert.Equal(baseCfg.IdleBetweenActions, merged.IdleBetweenActions);
    }

    [Fact]
    public void With_UnknownKeys_DoNotThrow_AndLeaveConfigValid()
    {
        var baseCfg = new HumanConfig();
        var ex = Record.Exception(() => baseCfg.With(new Dictionary<string, object>
        {
            ["totally_unknown_key"] = 5,
            ["another_bogus_one"] = "x",
            ["typing_delay"] = 88.0, // a valid one alongside the junk
        }));

        Assert.Null(ex);
        Assert.Equal(88, baseCfg.With(new Dictionary<string, object>
        {
            ["totally_unknown_key"] = 5,
            ["typing_delay"] = 88.0,
        }).TypingDelay);
    }
}
