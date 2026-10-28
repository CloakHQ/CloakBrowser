namespace CloakBrowser.Human;

/// <summary>
/// Random and timing utilities for the humanize layer.
/// Mirrors the helpers at the bottom of Python <c>cloakbrowser/human/config.py</c>
/// (<c>rand</c>, <c>rand_int</c>, <c>rand_range</c>, <c>rand_int_range</c>,
/// <c>sleep_ms</c>), plus a <c>Choice</c> helper used by
/// the keyboard mistype simulation.
/// </summary>
/// <remarks>
/// Uses a thread-safe shared <see cref="System.Random"/>. .NET's
/// <c>Random.Shared</c> (introduced in .NET 6) is already thread-safe, so we
/// delegate to it directly rather than locking a private instance.
/// </remarks>
public static class HumanRandom
{
    private static System.Random Rng => System.Random.Shared;

    /// <summary>Random double in [0.0, 1.0).</summary>
    public static double NextDouble() => Rng.NextDouble();

    /// <summary>Random float in [lo, hi] (inclusive), like Python's <c>random.uniform</c>.</summary>
    public static double Rand(double lo, double hi)
    {
        if (hi < lo)
            (lo, hi) = (hi, lo);
        return lo + Rng.NextDouble() * (hi - lo);
    }

    /// <summary>Random integer in [lo, hi] inclusive, like Python's <c>random.randint</c>.</summary>
    public static int RandInt(int lo, int hi)
    {
        if (hi < lo)
            (lo, hi) = (hi, lo);
        // Random.Next upper bound is exclusive - add 1 for inclusive range.
        return Rng.Next(lo, hi + 1);
    }

    /// <summary>Random float from a <see cref="Range"/> (min, max), inclusive.</summary>
    public static double RandRange(Range r) => Rand(r.Min, r.Max);

    /// <summary>Random integer from a <see cref="Range"/> (min, max), inclusive.</summary>
    public static int RandIntRange(Range r) => RandInt((int)r.Min, (int)r.Max);

    private const double Z95 = 1.6449; // standard normal 95th percentile

    /// <summary>Standard normal sample (Box-Muller).</summary>
    public static double Gauss()
    {
        double u = 0;
        while (u == 0) u = Rng.NextDouble();
        return Math.Sqrt(-2 * Math.Log(u)) * Math.Cos(2 * Math.PI * Rng.NextDouble());
    }

    /// <summary>
    /// Log-normal sample with <paramref name="r"/> as its ~5th / 95th percentiles, clipped
    /// to [low / 2, high * 2]. Human timings (key holds, gaps) are right-skewed like this,
    /// not uniform. Falls back to uniform when a bound is not positive.
    /// </summary>
    public static double RandLog(Range r)
    {
        double lo = r.Min, hi = r.Max;
        if (hi < lo) (lo, hi) = (hi, lo);
        if (lo <= 0) return Rand(lo, hi);
        if (hi == lo) return lo;
        double mu = (Math.Log(lo) + Math.Log(hi)) / 2;
        double sigma = (Math.Log(hi) - Math.Log(lo)) / (2 * Z95);
        return Math.Min(hi * 2, Math.Max(lo / 2, Math.Exp(mu + sigma * Gauss())));
    }

    /// <summary>Log-normal sample with the given median and log-space sigma.</summary>
    public static double RandLognormal(double median, double sigma)
    {
        if (median <= 0) return 0;
        if (sigma <= 0) return median;
        return median * Math.Exp(sigma * Gauss());
    }

    /// <summary>Return <c>true</c> with the given probability in [0, 1].</summary>
    public static bool Chance(double probability) => Rng.NextDouble() < probability;

    /// <summary>Pick a random character from a non-empty string, like Python's <c>random.choice</c>.</summary>
    public static char Choice(string options)
    {
        if (string.IsNullOrEmpty(options))
            throw new ArgumentException("Cannot choose from an empty string.", nameof(options));
        return options[Rng.Next(options.Length)];
    }

    /// <summary>Pick a random element from a non-empty list, like Python's <c>random.choice</c>.</summary>
    public static T Choice<T>(IReadOnlyList<T> options)
    {
        if (options == null || options.Count == 0)
            throw new ArgumentException("Cannot choose from an empty collection.", nameof(options));
        return options[Rng.Next(options.Count)];
    }

    /// <summary>Block the current thread for <paramref name="ms"/> milliseconds (no-op if &lt;= 0).</summary>
    public static void SleepMs(double ms)
    {
        if (ms > 0)
            Thread.Sleep((int)Math.Round(ms));
    }

    /// <summary>Asynchronously wait for <paramref name="ms"/> milliseconds (no-op if &lt;= 0).</summary>
    public static Task SleepMsAsync(double ms)
    {
        if (ms <= 0)
            return Task.CompletedTask;
        return Task.Delay((int)Math.Round(ms));
    }
}
